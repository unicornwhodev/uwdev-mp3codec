// SPDX-License-Identifier: MIT
#include "dsp.hpp"
#include "resampler.hpp"
#include "synthesis.hpp"
#include "synthesis_window.hpp"
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <vector>

namespace {
constexpr double pi = 3.141592653589793238462643383279502884;
void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

// Test-only, direct inverse equations. The production analysis factors the
// polyphase transpose, whereas this oracle explicitly implements synthesis
// matrixing, a 1024-value FIFO, U selection and the 16-phase window sum.
class ReferenceSynthesis {
public:
    ReferenceSynthesis() {
        for (std::size_t n=0;n<64;++n) for (std::size_t k=0;k<32;++k)
            matrix_[n][k] = std::cos(pi/64.0*static_cast<double>((n+16)*(2*k+1)));
        for (std::size_t n=0;n<36;++n) for (std::size_t k=0;k<18;++k)
            long_[n][k] = std::cos(pi/72.0*static_cast<double>((2*n+19)*(2*k+1)));
        for (std::size_t n=0;n<12;++n) for (std::size_t k=0;k<6;++k)
            short_[n][k] = std::cos(pi/24.0*static_cast<double>((2*n+7)*(2*k+1)));
    }

    std::array<double,576> decode(uwdev::mp3codec::Spectrum spectrum) {
        const int type=static_cast<int>(spectrum.block_type);
        if (type!=2) {
            constexpr std::array<double,8> c = {-.6,-.535,-.33,-.185,-.095,-.041,-.0142,-.0037};
            for (std::size_t sb=1;sb<32;++sb) for (std::size_t i=0;i<8;++i) {
                const double cs=1/std::sqrt(1+c[i]*c[i]);
                const double ca=c[i]*cs;
                const std::size_t lo=sb*18-1-i,hi=sb*18+i;
                const double a=spectrum.values[lo],b=spectrum.values[hi];
                spectrum.values[lo]=a*cs-b*ca;
                spectrum.values[hi]=b*cs+a*ca;
            }
        }
        std::array<std::array<double,18>,32> subbands{};
        for (std::size_t sb=0;sb<32;++sb) {
            std::array<double,36> buffer{};
            if (type==2) {
                for (std::size_t w=0;w<3;++w) for (std::size_t n=0;n<12;++n) {
                    double value=0;
                    for (std::size_t k=0;k<6;++k) value+=spectrum.values[sb*18+3*k+w]*short_[n][k];
                    buffer[6+6*w+n]+=value*std::sin(pi/12.0*(static_cast<double>(n)+.5));
                }
            } else {
                for (std::size_t n=0;n<36;++n) {
                    double value=0;
                    for (std::size_t k=0;k<18;++k) value+=spectrum.values[sb*18+k]*long_[n][k];
                    double window=std::sin(pi/36.0*(static_cast<double>(n)+.5));
                    if (type==1 && n>=18) {
                        if(n<24)window=1;else if(n<30)window=std::sin(pi/12.0*(static_cast<double>(n)-17.5));else window=0;
                    }
                    if (type==3 && n<18) {
                        if(n<6)window=0;else if(n<12)window=std::sin(pi/12.0*(static_cast<double>(n)-5.5));else window=1;
                    }
                    buffer[n]=value*window;
                }
            }
            for (std::size_t n=0;n<18;++n) {
                subbands[sb][n]=buffer[n]+overlap_[sb][n];
                if (sb%2!=0 && n%2!=0) subbands[sb][n]*=-1;
                overlap_[sb][n]=buffer[n+18];
            }
        }
        std::array<double,576> pcm{};
        for (std::size_t slot=0;slot<18;++slot) {
            std::move_backward(fifo_.begin(),fifo_.end()-64,fifo_.end());
            for (std::size_t n=0;n<64;++n) {
                fifo_[n]=0;
                for (std::size_t k=0;k<32;++k)fifo_[n]+=subbands[k][slot]*matrix_[n][k];
            }
            for (std::size_t j=0;j<32;++j) {
                double sample=0;
                for (std::size_t phase=0;phase<8;++phase) {
                    const auto& d=uwdev::mp3codec::detail::synthesis_window_q16;
                    sample+=fifo_[128*phase+j]*static_cast<double>(d[64*phase+j])/65536;
                    sample+=fifo_[128*phase+96+j]*static_cast<double>(d[64*phase+32+j])/65536;
                }
                pcm[32*slot+j]=sample;
            }
        }
        return pcm;
    }
private:
    std::array<std::array<double,32>,64> matrix_{};
    std::array<std::array<double,18>,36> long_{};
    std::array<std::array<double,6>,12> short_{};
    std::array<std::array<double,18>,32> overlap_{};
    std::array<double,1024> fifo_{};
};

double roundtrip(bool switching) {
    constexpr std::size_t granules=80;
    std::vector<double> source((granules+3)*576,0);
    std::uint32_t state=12345;
    for (std::size_t i=0;i<granules*576;++i) {
        state=1664525U*state+1013904223U;
        source[i]=(static_cast<double>(state)/4294967296.0-.5)*.4;
    }
    uwdev::mp3codec::AnalysisBank analysis;
    ReferenceSynthesis synthesis;
    uwdev::mp3codec::SynthesisMonitor monitor;
    std::vector<double> decoded;
    std::array<bool,4> used{};
    for (std::size_t gr=0;gr<granules+3;++gr) {
        std::array<double,576> pcm{};
        std::copy_n(source.begin()+static_cast<std::ptrdiff_t>(gr*576),576,pcm.begin());
        const auto spectrum=analysis.process(pcm,switching && (gr%9==1 || gr%9==2));
        used[static_cast<std::size_t>(spectrum.block_type)]=true;
        const auto output=synthesis.decode(spectrum);
        const auto monitored=monitor.process(spectrum);
        for(std::size_t i=0;i<576;++i)require(std::abs(output[i]-monitored[i])<1e-12,"production inverse differs from independent direct oracle");
        decoded.insert(decoded.end(),output.begin(),output.end());
    }
    if (switching) require(std::all_of(used.begin(),used.end(),[](bool v){return v;}),"missing hybrid block transition");
    double energy=0,error=0;
    for (std::size_t i=2048;i<granules*576-2048;++i) {
        const double difference=source[i]-decoded[i+1056];
        energy+=source[i]*source[i];error+=difference*difference;
    }
    const double snr=10*std::log10(energy/error);
    require(snr>78,"unquantized hybrid/filterbank roundtrip is inaccurate");
    return snr;
}

void check_resampler() {
    uwdev::mp3codec::Decimator2 full,chunked;
    std::array<double,1001> source{};
    for(std::size_t i=0;i<source.size();++i)source[i]=.5*std::sin(2*pi*997*static_cast<double>(i)/96000);
    auto expected=full.push(source.data(),source.size());
    auto tail=full.finish();expected.insert(expected.end(),tail.begin(),tail.end());
    std::vector<double> actual;
    for(std::size_t i=0;i<source.size();++i) {
        auto next=chunked.push(source.data()+i,1);actual.insert(actual.end(),next.begin(),next.end());
    }
    tail=chunked.finish();actual.insert(actual.end(),tail.begin(),tail.end());
    require(expected==actual,"resampler depends on input chunk boundaries");
    require(actual.size()==596,"resampler output length or tail is incorrect");
    require(chunked.finish().empty(),"resampler double finish emitted extra samples");
    bool rejected=false;try {chunked.push(source.data(),1);}catch(const std::logic_error&){rejected=true;}
    require(rejected,"resampler accepted input after finish");
    const auto& taps=full.coefficients();double sum=0,centroid=0;
    for(std::size_t i=0;i<taps.size();++i) {
        sum+=taps[i];centroid+=static_cast<double>(i)*taps[i];
        require(std::abs(taps[i]-taps[taps.size()-1-i])<1e-15,"FIR is not symmetric");
    }
    require(std::abs(sum-1)<1e-12,"FIR has non-unity DC gain");
    require(std::abs(centroid/sum-95.5)<1e-10,"FIR group delay is incorrect");
    for(const int frequency : {1000,10000,20000,24000,26000,30000,40000}) {
        double real=0,imaginary=0;
        for(std::size_t i=0;i<taps.size();++i) {
            const double phase=2*pi*frequency*static_cast<double>(i)/96000;
            real+=taps[i]*std::cos(phase);imaginary+=taps[i]*std::sin(phase);
        }
        const double db=20*std::log10(std::hypot(real,imaginary));
        if(frequency<=20000)require(std::abs(db)<.01,"FIR passband accuracy is insufficient");
        else require(db<-80,"FIR anti-alias stopband is insufficient");
    }
    uwdev::mp3codec::Decimator2 impulse_filter;std::array<double,1> impulse{1};
    auto impulse_output=impulse_filter.push(impulse.data(),1);tail=impulse_filter.finish();
    impulse_output.insert(impulse_output.end(),tail.begin(),tail.end());
    require(impulse_output.size()==96,"FIR impulse tail was truncated");
    for(std::size_t i=0;i<96;++i)require(impulse_output[i]==taps[i*2],"FIR impulse response is incorrect");

    // A failed bounded operation must be retryable without losing phase/history.
    uwdev::mp3codec::Decimator2 bounded;
    std::array<double,501> buffer{};
    bool capacity_rejected=false;
    try {bounded.push_into(source.data(),source.size(),buffer.data(),500);}
    catch(const std::invalid_argument&){capacity_rejected=true;}
    require(capacity_rejected,"undersized resampler output was accepted");
    auto bad=source;bad.back()=std::numeric_limits<double>::quiet_NaN();
    bool nan_rejected=false;
    try {bounded.push_into(bad.data(),bad.size(),buffer.data(),buffer.size());}
    catch(const std::invalid_argument&){nan_rejected=true;}
    require(nan_rejected,"non-finite input was accepted");
    const auto written=bounded.push_into(source.data(),source.size(),buffer.data(),buffer.size());
    require(written==501 && std::equal(buffer.begin(),buffer.end(),expected.begin()),"failed push changed resampler state");
    bool tail_rejected=false;
    try {bounded.finish_into(buffer.data(),94);}
    catch(const std::invalid_argument&){tail_rejected=true;}
    require(tail_rejected,"undersized tail buffer was accepted");
    const auto drained=bounded.finish_into(buffer.data(),buffer.size());
    require(drained==95 && std::equal(buffer.begin(),buffer.begin()+95,expected.begin()+501),"failed finish changed resampler state");
    require(bounded.finish_into(nullptr,0)==0,"bounded finish is not idempotent");
}
}

int main() {
    try {
        const double long_snr=roundtrip(false),switching_snr=roundtrip(true);
        check_resampler();
        std::array<double,576> silence{},step{};step.fill(.2);
        require(uwdev::mp3codec::AnalysisBank::transient_between(silence,step),"missed transient at granule boundary");
        require(!uwdev::mp3codec::AnalysisBank::transient_between(step,step),"stationary signal marked transient");
        std::cout<<"DSP checks passed; random broadband roundtrip SNR long="<<long_snr
                 <<" dB, switching="<<switching_snr<<" dB; delay=1056; FIR delay=95.5 input samples\n";
        return 0;
    }catch(const std::exception& e){std::cerr<<"DSP check failed: "<<e.what()<<'\n';return 1;}
}
