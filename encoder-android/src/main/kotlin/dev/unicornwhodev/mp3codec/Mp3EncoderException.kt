// SPDX-License-Identifier: MIT
package dev.unicornwhodev.mp3codec

open class Mp3EncoderException @JvmOverloads constructor(
    message: String,
    cause: Throwable? = null,
) : RuntimeException(message, cause)

class Mp3ConfigurationException @JvmOverloads constructor(message: String, cause: Throwable? = null) :
    Mp3EncoderException(message, cause)
class Mp3InputException @JvmOverloads constructor(message: String, cause: Throwable? = null) :
    Mp3EncoderException(message, cause)
class Mp3EncodingException @JvmOverloads constructor(message: String, cause: Throwable? = null) :
    Mp3EncoderException(message, cause)
class Mp3OutputException @JvmOverloads constructor(message: String, cause: Throwable? = null) :
    Mp3EncoderException(message, cause)
class Mp3CancelledException @JvmOverloads constructor(message: String = "Encoding was cancelled", cause: Throwable? = null) :
    Mp3EncoderException(message, cause)
class Mp3NativeException @JvmOverloads constructor(message: String, cause: Throwable? = null) :
    Mp3EncoderException(message, cause)
class Mp3StateException @JvmOverloads constructor(message: String, cause: Throwable? = null) :
    Mp3EncoderException(message, cause)
