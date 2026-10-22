// SPDX-License-Identifier: MIT
#include <jni.h>
#include <cstring>

#include <algorithm>
#include <array>
#include <cstdint>
#include <exception>
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>

#include "codec/encoder.hpp"

namespace {

constexpr std::size_t kTransferBytes = 32U * 1024U;
struct JavaExceptionPending final {};

void check_java(JNIEnv* env) {
    if (env->ExceptionCheck() == JNI_TRUE) throw JavaExceptionPending{};
}

void throw_java(JNIEnv* env, const char* class_name, const char* message) noexcept {
    if (env->ExceptionCheck() == JNI_TRUE) return;
    jclass cls = env->FindClass(class_name);
    if (cls == nullptr) return;
    env->ThrowNew(cls, message);
    env->DeleteLocalRef(cls);
}

void map_exception(JNIEnv* env, bool configuration = false) noexcept {
    try {
        throw;
    } catch (const JavaExceptionPending&) {
        // Preserve the exact Java throwable (including OutputStream's original cause).
    } catch (const uwdev::mp3codec::Cancelled& failure) {
        throw_java(env, "dev/unicornwhodev/mp3codec/Mp3CancelledException", failure.what());
    } catch (const std::invalid_argument& failure) {
        throw_java(env, configuration ? "dev/unicornwhodev/mp3codec/Mp3ConfigurationException"
                                      : "dev/unicornwhodev/mp3codec/Mp3InputException", failure.what());
    } catch (const std::bad_alloc&) {
        throw_java(env, "dev/unicornwhodev/mp3codec/Mp3NativeException", "Native encoder allocation failed");
    } catch (const std::runtime_error& failure) {
        throw_java(env, "dev/unicornwhodev/mp3codec/Mp3EncodingException", failure.what());
    } catch (const std::exception& failure) {
        throw_java(env, "dev/unicornwhodev/mp3codec/Mp3NativeException", failure.what());
    } catch (...) {
        throw_java(env, "dev/unicornwhodev/mp3codec/Mp3NativeException", "Unknown native encoder error");
    }
}

// No mutable process-global registry: the Kotlin operation lease owns this pointer.
// Only request_cancel() is allowed concurrently with a native write/finish call.
class Session final {
public:
    Session(JNIEnv* env, jobject output, const uwdev::mp3codec::Config& config) : channels_(config.channels) {
        if (env->GetJavaVM(&vm_) != JNI_OK) throw std::runtime_error("Cannot acquire Java VM");
        output_ = env->NewGlobalRef(output);
        check_java(env);
        if (output_ == nullptr) throw std::bad_alloc();
        try {
            jclass cls = env->GetObjectClass(output);
            check_java(env);
            write_method_ = env->GetMethodID(cls, "write", "([BII)V");
            env->DeleteLocalRef(cls);
            check_java(env);
            if (write_method_ == nullptr) throw std::runtime_error("OutputStream.write is unavailable");
            jbyteArray local_buffer = env->NewByteArray(static_cast<jsize>(kTransferBytes));
            check_java(env);
            if (local_buffer == nullptr) throw std::bad_alloc();
            buffer_ = static_cast<jbyteArray>(env->NewGlobalRef(local_buffer));
            env->DeleteLocalRef(local_buffer);
            check_java(env);
            if (buffer_ == nullptr) throw std::bad_alloc();
            encoder_ = std::make_unique<uwdev::mp3codec::Encoder>(config,
                [this](const std::uint8_t* data, std::size_t count) { write_output(data, count); });
        } catch (...) {
            release_refs(env);
            throw;
        }
    }

    ~Session() noexcept {
        encoder_.reset();
        JNIEnv* env = nullptr;
        bool attached = false;
        if (vm_->GetEnv(reinterpret_cast<void**>(&env), JNI_VERSION_1_6) != JNI_OK) {
#if defined(__ANDROID__)
            if (vm_->AttachCurrentThread(&env, nullptr) != JNI_OK) return;
#else
            if (vm_->AttachCurrentThread(reinterpret_cast<void**>(&env), nullptr) != JNI_OK) return;
#endif
            attached = true;
        }
        release_refs(env);
        if (attached) vm_->DetachCurrentThread();
    }

    Session(const Session&) = delete;
    Session& operator=(const Session&) = delete;

    void write(JNIEnv* env, jbyteArray bytes, jint offset, jint length) {
        if (bytes == nullptr) throw std::invalid_argument("PCM array is null");
        const jsize size = env->GetArrayLength(bytes);
        if (offset < 0 || length < 0 || offset > size || length > size - offset || length % (2 * channels_) != 0) {
            throw std::invalid_argument("Invalid PCM slice or incomplete interleaved frame");
        }
        ActiveEnvironment active(*this, env);
        // GetByteArrayRegion initializes exactly the slice consumed below.
        // Avoid clearing 32 KiB for each single-frame input call.
        std::array<std::uint8_t, kTransferBytes> input;
        jint position = offset;
        jint remaining = length;
        while (remaining > 0) {
            const jint count = std::min(remaining, static_cast<jint>(input.size()));
            env->GetByteArrayRegion(bytes, position, count, reinterpret_cast<jbyte*>(input.data()));
            check_java(env);
            encoder_->write_pcm16le(input.data(), static_cast<std::size_t>(count));
            position += count;
            remaining -= count;
        }
    }

    uwdev::mp3codec::Stats finish(JNIEnv* env) {
        ActiveEnvironment active(*this, env);
        return encoder_->finish();
    }

    void cancel() noexcept { encoder_->request_cancel(); }

private:
    class ActiveEnvironment final {
    public:
        ActiveEnvironment(Session& owner, JNIEnv* env) : owner_(owner) { owner_.active_env_ = env; }
        ~ActiveEnvironment() { owner_.active_env_ = nullptr; }
        ActiveEnvironment(const ActiveEnvironment&) = delete;
        ActiveEnvironment& operator=(const ActiveEnvironment&) = delete;
    private:
        Session& owner_;
    };

    void release_refs(JNIEnv* env) noexcept {
        if (buffer_ != nullptr) env->DeleteGlobalRef(buffer_);
        if (output_ != nullptr) env->DeleteGlobalRef(output_);
        buffer_ = nullptr;
        output_ = nullptr;
    }

    void write_output(const std::uint8_t* data, std::size_t count) {
        if (active_env_ == nullptr) throw std::logic_error("Output attempted outside an encoding operation");
        while (count > 0) {
            const auto chunk = static_cast<jsize>(std::min(count, kTransferBytes));
            active_env_->SetByteArrayRegion(buffer_, 0, chunk, reinterpret_cast<const jbyte*>(data));
            check_java(active_env_);
            active_env_->CallVoidMethod(output_, write_method_, buffer_, 0, chunk);
            check_java(active_env_);
            data += static_cast<std::size_t>(chunk);
            count -= static_cast<std::size_t>(chunk);
        }
    }

    JavaVM* vm_ = nullptr;
    jobject output_ = nullptr;
    jbyteArray buffer_ = nullptr;
    jmethodID write_method_ = nullptr;
    JNIEnv* active_env_ = nullptr;
    int channels_;
    std::unique_ptr<uwdev::mp3codec::Encoder> encoder_;
};

Session& session(jlong handle) {
    if (handle == 0) throw std::invalid_argument("Native session is closed");
    return *reinterpret_cast<Session*>(static_cast<std::intptr_t>(handle));
}

jlong JNICALL native_create(JNIEnv* env, jclass, jint rate, jint channels, jint bitrate, jobject output) {
    try {
        if (output == nullptr) throw std::invalid_argument("OutputStream is null");
        auto value = std::make_unique<Session>(env, output, uwdev::mp3codec::Config{rate, channels, bitrate});
        return static_cast<jlong>(reinterpret_cast<std::intptr_t>(value.release()));
    } catch (...) {
        map_exception(env, true);
        return 0;
    }
}

void JNICALL native_write(JNIEnv* env, jclass, jlong handle, jbyteArray bytes, jint offset, jint length) {
    try { session(handle).write(env, bytes, offset, length); }
    catch (...) { map_exception(env); }
}

jlong checked_counter(std::uint64_t value) {
    if (value > static_cast<std::uint64_t>(std::numeric_limits<jlong>::max())) {
        throw std::overflow_error("Encoding statistics exceed Kotlin Long range");
    }
    return static_cast<jlong>(value);
}

jlongArray JNICALL native_finish(JNIEnv* env, jclass, jlong handle) {
    try {
        const auto stats = session(handle).finish(env);
        const auto bits=[](double value){jlong result;static_assert(sizeof(result)==sizeof(value));std::memcpy(&result,&value,sizeof(value));return result;};
        const std::array<jlong, 9> values{
            checked_counter(stats.input_frames), checked_counter(stats.output_bytes),
            static_cast<jlong>(stats.output_sample_rate), static_cast<jlong>(stats.bitrate_kbps),
            static_cast<jlong>(stats.channels), checked_counter(stats.encoded_mpeg_frames),
            bits(stats.reconstructed_peak),checked_counter(stats.peak_protected_frames),bits(stats.minimum_peak_gain)};
        jlongArray result = env->NewLongArray(static_cast<jsize>(values.size()));
        check_java(env);
        if (result == nullptr) throw std::bad_alloc();
        env->SetLongArrayRegion(result, 0, static_cast<jsize>(values.size()), values.data());
        return result;
    } catch (...) {
        map_exception(env);
        return nullptr;
    }
}

void JNICALL native_cancel(JNIEnv* env, jclass, jlong handle) {
    try { session(handle).cancel(); }
    catch (...) { map_exception(env); }
}

void JNICALL native_destroy(JNIEnv*, jclass, jlong handle) {
    delete reinterpret_cast<Session*>(static_cast<std::intptr_t>(handle));
}

} // namespace

extern "C" JNIEXPORT jint JNICALL JNI_OnLoad(JavaVM* vm, void*) {
    JNIEnv* env = nullptr;
    if (vm->GetEnv(reinterpret_cast<void**>(&env), JNI_VERSION_1_6) != JNI_OK) return JNI_ERR;
    jclass cls = env->FindClass("dev/unicornwhodev/mp3codec/NativeBridge");
    if (cls == nullptr) return JNI_ERR;
    const JNINativeMethod methods[]{
        {const_cast<char*>("create"), const_cast<char*>("(IIILjava/io/OutputStream;)J"), reinterpret_cast<void*>(native_create)},
        {const_cast<char*>("write"), const_cast<char*>("(J[BII)V"), reinterpret_cast<void*>(native_write)},
        {const_cast<char*>("finish"), const_cast<char*>("(J)[J"), reinterpret_cast<void*>(native_finish)},
        {const_cast<char*>("cancel"), const_cast<char*>("(J)V"), reinterpret_cast<void*>(native_cancel)},
        {const_cast<char*>("destroy"), const_cast<char*>("(J)V"), reinterpret_cast<void*>(native_destroy)},
    };
    const jint result = env->RegisterNatives(cls, methods, static_cast<jint>(sizeof(methods) / sizeof(methods[0])));
    env->DeleteLocalRef(cls);
    return result == JNI_OK ? JNI_VERSION_1_6 : JNI_ERR;
}
