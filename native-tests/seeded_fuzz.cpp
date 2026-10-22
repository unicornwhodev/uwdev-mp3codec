// SPDX-License-Identifier: MIT
// Bounded deterministic fuzz corpus. This is not a coverage-guided fuzz claim.
#include "codec/encoder.hpp"
#include <algorithm>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <vector>

namespace {
std::uint32_t state=0x22A01026U;
std::uint32_t random_word() { state^=state<<13U;state^=state>>17U;state^=state<<5U;return state; }
void require(bool value,const char* message) {if(!value)throw std::runtime_error(message);}
std::vector<std::uint8_t> render(uwdev::mp3codec::Config config,const std::vector<std::uint8_t>& pcm,bool fragmented) {
    std::vector<std::uint8_t> result;
    uwdev::mp3codec::Encoder encoder(config,[&](const std::uint8_t* p,std::size_t n) {
        require(n>0 && n<=32768,"unbounded output block");result.insert(result.end(),p,p+n);
    });
    const auto frame_bytes=static_cast<std::size_t>(config.channels)*2;
    for(std::size_t offset=0;offset<pcm.size();) {
        const auto count=fragmented ? std::min(pcm.size()-offset,frame_bytes*(1+random_word()%257)) : pcm.size();
        encoder.write_pcm16le(pcm.data()+offset,count);offset+=count;
        encoder.write_pcm16le(nullptr,0);
    }
    const auto stats=encoder.finish();
    require(stats.input_frames==pcm.size()/frame_bytes,"fuzz input counter mismatch");
    require(stats.output_bytes==result.size(),"fuzz output counter mismatch");
    require(stats.minimum_peak_gain>0,"peak guard erased a frame");
    require(stats.reconstructed_peak<=.995001,"peak guard exceeded its reconstruction ceiling");
    require(encoder.finish().output_bytes==stats.output_bytes,"fuzz finish not idempotent");
    return result;
}
}
int main() {
    std::size_t cases=0;
    try {
        for(int rate:{44100,48000,96000})for(int channels:{1,2})for(int kbps:{128,192,256,320}) {
            const uwdev::mp3codec::Config config{rate,channels,kbps};
            for(int trial=0;trial<12;++trial) {
                const auto frames=1+random_word()%6144;
                std::vector<std::uint8_t> pcm(static_cast<std::size_t>(frames)*static_cast<std::size_t>(channels)*2);
                for(auto& byte:pcm)byte=static_cast<std::uint8_t>(random_word());
                if(trial%4==0)std::fill(pcm.begin(),pcm.end(),0);
                const auto whole=render(config,pcm,false);
                require(whole==render(config,pcm,true),"chunk-dependent fuzz output");
                bool failed=false;
                try {
                    uwdev::mp3codec::Encoder encoder(config,[](const std::uint8_t*,std::size_t){throw std::runtime_error("seeded sink failure");});
                    encoder.write_pcm16le(pcm.data(),pcm.size());encoder.finish();
                }catch(const std::runtime_error&){failed=true;}
                require(failed,"injected sink failure lost");
                uwdev::mp3codec::Encoder cancelled(config,[](const std::uint8_t*,std::size_t){});
                cancelled.request_cancel();bool rejected=false;
                try {cancelled.write_pcm16le(pcm.data(),pcm.size());}catch(const uwdev::mp3codec::Cancelled&){rejected=true;}
                require(rejected,"cancelled fuzz operation accepted");
                ++cases;
                if(cases%24==0)std::cout<<"seeded fuzz progress "<<cases<<" / 288\n"<<std::flush;
            }
        }
        std::cout<<"{\"status\":\"PASS\",\"seed\":\"0x22A01026\",\"cases\":"<<cases<<",\"coverage_guided\":false}\n";
        return 0;
    }catch(const std::exception& e){std::cerr<<"seeded fuzz failure after "<<cases<<" cases: "<<e.what()<<'\n';return 1;}
}
