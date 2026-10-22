// SPDX-License-Identifier: MIT
// Original direct inverse equations. Window numbers retain the pl_mpeg MIT credit.
#include "synthesis.hpp"
#include "synthesis_window.hpp"
#include <algorithm>
#include <cmath>

namespace uwdev::mp3codec {
namespace {
constexpr double pi=3.141592653589793238462643383279502884;
struct Tables {
    std::array<std::array<double,32>,64> matrix{};
    std::array<std::array<double,18>,36> long_mdct{};
    std::array<std::array<double,6>,12> short_mdct{};
    std::array<std::array<double,36>,4> windows{};
    std::array<double,81> interpolation{};
    Tables() {
        for(std::size_t n=0;n<64;++n)for(std::size_t k=0;k<32;++k)matrix[n][k]=std::cos(pi/64.0*static_cast<double>((n+16)*(2*k+1)));
        for(std::size_t n=0;n<36;++n)for(std::size_t k=0;k<18;++k)long_mdct[n][k]=std::cos(pi/72.0*static_cast<double>((2*n+19)*(2*k+1)));
        for(std::size_t n=0;n<12;++n)for(std::size_t k=0;k<6;++k)short_mdct[n][k]=std::cos(pi/24.0*static_cast<double>((2*n+7)*(2*k+1)));
        for(std::size_t type=0;type<4;++type)for(std::size_t n=0;n<36;++n) {
            double w=std::sin(pi/36.0*(static_cast<double>(n)+.5));
            if(type==1 && n>=18)w=n<24 ? 1.0 : (n<30 ? std::sin(pi/12.0*(static_cast<double>(n)-17.5)) : 0.0);
            if(type==3 && n<18)w=n<6 ? 0.0 : (n<12 ? std::sin(pi/12.0*(static_cast<double>(n)-5.5)) : 1.0);
            windows[type][n]=w;
        }
        auto i0=[](double x){double sum=1,term=1;for(int k=1;k<=64;++k){term*=x*x/(4.0*k*k);sum+=term;if(term<sum*1e-17)break;}return sum;};
        double sum=0;
        for(std::size_t n=0;n<81;++n) {
            const double x=(static_cast<double>(n)-40)/4,r=(static_cast<double>(n)-40)/40;
            const double sinc=x==0 ? 1 : std::sin(pi*x)/(pi*x);
            interpolation[n]=sinc*i0(5*std::sqrt(1-r*r))/i0(5);sum+=interpolation[n];
        }
        for(auto& h:interpolation)h*=4/sum;
    }
};
const Tables& tables(){static const Tables t;return t;}
}
std::array<double,576> SynthesisMonitor::process(Spectrum spectrum) {
    const auto& t=tables();const auto type=static_cast<std::size_t>(spectrum.block_type);
    if(type!=2) {
        constexpr std::array<double,8> c{-.6,-.535,-.33,-.185,-.095,-.041,-.0142,-.0037};
        for(std::size_t sb=1;sb<32;++sb)for(std::size_t i=0;i<8;++i) {
            const double cs=1/std::sqrt(1+c[i]*c[i]),ca=c[i]*cs;
            const auto lo=sb*18-1-i,hi=sb*18+i;const double a=spectrum.values[lo],b=spectrum.values[hi];
            spectrum.values[lo]=a*cs-b*ca;spectrum.values[hi]=b*cs+a*ca;
        }
    }
    std::array<std::array<double,18>,32> subbands{};
    for(std::size_t sb=0;sb<32;++sb) {
        std::array<double,36> buffer{};
        if(type==2) {
            for(std::size_t w=0;w<3;++w)for(std::size_t n=0;n<12;++n) {
                double v=0;for(std::size_t k=0;k<6;++k)v+=spectrum.values[sb*18+3*k+w]*t.short_mdct[n][k];
                buffer[6+6*w+n]+=v*std::sin(pi/12.0*(static_cast<double>(n)+.5));
            }
        } else {
            for(std::size_t n=0;n<36;++n) {
                double v=0;for(std::size_t k=0;k<18;++k)v+=spectrum.values[sb*18+k]*t.long_mdct[n][k];
                buffer[n]=v*t.windows[type][n];
            }
        }
        for(std::size_t n=0;n<18;++n) {
            subbands[sb][n]=buffer[n]+overlap_[sb][n];
            if(sb%2 && n%2)subbands[sb][n]*=-1;
            overlap_[sb][n]=buffer[n+18];
        }
    }
    std::array<double,576> pcm{};
    for(std::size_t slot=0;slot<18;++slot) {
        std::move_backward(fifo_.begin(),fifo_.end()-64,fifo_.end());
        for(std::size_t n=0;n<64;++n) {
            fifo_[n]=0;for(std::size_t k=0;k<32;++k)fifo_[n]+=subbands[k][slot]*t.matrix[n][k];
        }
        for(std::size_t j=0;j<32;++j) {
            double value=0;
            for(std::size_t phase=0;phase<8;++phase) {
                const auto& d=detail::synthesis_window_q16;
                value+=fifo_[128*phase+j]*static_cast<double>(d[64*phase+j])/65536;
                value+=fifo_[128*phase+96+j]*static_cast<double>(d[64*phase+32+j])/65536;
            }
            pcm[32*slot+j]=value;
        }
    }
    return pcm;
}
double SynthesisMonitor::peak(const Spectrum& spectrum) {
    const auto pcm=process(spectrum);const auto& h=tables().interpolation;double maximum=0;
    for(double sample:pcm) {
        maximum=std::max(maximum,std::abs(sample));interpolation_history_[interpolation_cursor_]=sample;
        for(std::size_t phase=0;phase<4;++phase) {
            double value=0;auto cursor=interpolation_cursor_;
            for(std::size_t tap=phase;tap<h.size();tap+=4) {
                value+=h[tap]*interpolation_history_[cursor];cursor=cursor==0 ? interpolation_history_.size()-1 : cursor-1;
            }
            maximum=std::max(maximum,std::abs(value));
        }
        interpolation_cursor_=(interpolation_cursor_+1)%interpolation_history_.size();
    }
    return maximum;
}
}
