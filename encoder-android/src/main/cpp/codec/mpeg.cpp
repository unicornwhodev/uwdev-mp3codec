// SPDX-License-Identifier: MIT
#include "mpeg.hpp"
#include "huffman_tables.hpp"
#include "synthesis.hpp"
#include <algorithm>
#include <array>
#include <cmath>
#include <deque>
#include <limits>
#include <stdexcept>
#include <utility>
#include <vector>

namespace uwdev::mp3codec {
namespace {
constexpr int kImpossible = 1000000;
constexpr int kMaxQuantized = 8206;
// Normative numerical band widths, represented as cumulative boundaries.
// Provenance: CC0 minimp3 g_scf_long/g_scf_short, MPEG-1 rows 5 and 6.
constexpr std::array<int,23> kLong44100{0,4,8,12,16,20,24,30,36,44,52,62,74,90,110,134,162,196,238,288,342,418,576};
constexpr std::array<int,23> kLong48000{0,4,8,12,16,20,24,30,36,42,50,60,72,88,106,128,156,190,230,276,330,384,576};
constexpr std::array<int,14> kShort44100{0,4,8,12,16,22,30,40,52,66,84,106,136,192};
constexpr std::array<int,14> kShort48000{0,4,8,12,16,22,28,38,50,64,80,100,126,192};
constexpr std::array<int,16> kSlen1{0,0,0,0,3,1,1,1,2,2,2,3,3,3,4,4};
constexpr std::array<int,16> kSlen2{0,1,2,3,0,1,2,3,1,2,3,1,2,3,2,3};

class BitWriter {
public:
    explicit BitWriter(std::size_t capacity = 0) { bytes_.reserve(capacity); }
    void put(std::uint32_t value, int count) {
        if (count < 0 || count > 32 || (count < 32 && (value >> count) != 0U))
            throw std::logic_error("MPEG bit field overflow");
        while (count > 0) {
            if ((bits_ & 7U) == 0U) bytes_.push_back(0);
            const int available=8-static_cast<int>(bits_ & 7U);
            const int take=std::min(available,count);
            const auto mask=(1U << take)-1U;
            bytes_.back() |= static_cast<std::uint8_t>(((value >> (count-take)) & mask) << (available-take));
            bits_+=static_cast<std::size_t>(take);
            count-=take;
        }
    }
    void append(const BitWriter& source) {
        const auto whole=source.bits_/8U;
        if ((bits_ & 7U) == 0U) {
            bytes_.insert(bytes_.end(),source.bytes_.begin(),source.bytes_.begin()+static_cast<std::ptrdiff_t>(whole));
            bits_+=whole*8U;
        } else {
            for (std::size_t i=0;i<whole;++i) put(source.bytes_[i],8);
        }
        const int tail=static_cast<int>(source.bits_ & 7U);
        if (tail) put(source.bytes_[whole] >> (8-tail),tail);
    }
    std::size_t bits() const noexcept { return bits_; }
    const std::vector<std::uint8_t>& bytes() const noexcept { return bytes_; }
private:
    std::vector<std::uint8_t> bytes_;
    std::size_t bits_=0;
};

struct Band {
    int first=0, last=0, scale_index=0;
    double threshold=0;
};
struct Prepared {
    std::array<double,576> values{}, powers75{};
    std::array<Band,39> bands{};
    int band_count=0;
    BlockType type=BlockType::Normal;
};

Prepared prepare(const Spectrum& spectrum, int sample_rate) {
    Prepared p;
    p.type=spectrum.block_type;
    if (p.type == BlockType::Short) {
        const auto& boundaries = sample_rate == 44100 ? kShort44100 : kShort48000;
        int destination=0;
        for (int band=0; band<13; ++band) {
            for (int window=0; window<3; ++window) {
                auto& b=p.bands[static_cast<std::size_t>(p.band_count++)];
                b.first=destination;
                b.scale_index=band*3+window;
                double energy=0, peak=0;
                for (int f=boundaries[static_cast<std::size_t>(band)]; f<boundaries[static_cast<std::size_t>(band+1)]; ++f) {
                    const int source=(f/6)*18+(f%6)*3+window;
                    const double value=spectrum.values[static_cast<std::size_t>(source)];
                    p.values[static_cast<std::size_t>(destination++)]=value;
                    energy+=value*value;
                    peak=std::max(peak, value*value);
                }
                b.last=destination;
                const double tonality=energy>0 ? peak/energy : 0;
                // Tonal short bands receive a stricter distortion threshold.
                b.threshold=std::max(1e-24, energy*(0.0015-0.0013*tonality));
            }
        }
    } else {
        const auto& boundaries=sample_rate == 44100 ? kLong44100 : kLong48000;
        p.values=spectrum.values;
        p.band_count=22;
        for (int band=0; band<22; ++band) {
            auto& b=p.bands[static_cast<std::size_t>(band)];
            b.first=boundaries[static_cast<std::size_t>(band)];
            b.last=boundaries[static_cast<std::size_t>(band+1)];
            b.scale_index=band;
            b.threshold=std::max(1e-24,spectrum.masking[static_cast<std::size_t>(band)]*static_cast<double>(b.last-b.first));
        }
    }
    for (std::size_t i=0; i<p.values.size(); ++i) {
        if (!std::isfinite(p.values[i])) throw std::invalid_argument("non-finite MPEG spectrum");
        p.powers75[i]=std::pow(std::abs(p.values[i]),0.75);
    }
    return p;
}

const std::array<double,kMaxQuantized+2>& powers43() {
    static const auto result=[] {
        std::array<double,kMaxQuantized+2> values{};
        for (std::size_t i=0; i<values.size(); ++i) values[i]=std::pow(static_cast<double>(i),4.0/3.0);
        return values;
    }();
    return result;
}

struct Quantized {
    std::array<int,576> samples{};
    std::array<int,39> scales{};
    std::array<double,39> noise_ratios{};
    BlockType type=BlockType::Normal;
    int gain=0, compress=0, scale_bits=0, bits=kImpossible;
    int big_end=0, count1_end=0, count1_table=0;
    int region0_count=0, region1_count=0;
    std::array<int,3> tables{};
    std::array<int,3> region_ends{};
    double score=std::numeric_limits<double>::infinity();
};

int pair_cost(int x, int y, int number) {
    x=std::abs(x); y=std::abs(y);
    const auto& t=detail::kHuffmanTables[static_cast<std::size_t>(number)];
    if (!t.codes) return kImpossible;
    if (number == 0) return (x == 0 && y == 0) ? 0 : kImpossible;
    const int maximum=t.linbits ? 15+((1<<t.linbits)-1) : t.dimension-1;
    if (x>maximum || y>maximum) return kImpossible;
    int cost=(x != 0)+(y != 0);
    if (t.linbits) {
        if (x>=15) cost+=t.linbits;
        if (y>=15) cost+=t.linbits;
        x=std::min(x,15); y=std::min(y,15);
    }
    return cost+t.codes[static_cast<std::size_t>(x*t.dimension+y)].length;
}

void choose_codebooks(Quantized& q, int sample_rate) {
    int last=575;
    while (last>=0 && q.samples[static_cast<std::size_t>(last)] == 0) --last;
    q.count1_end=((last+4)/4)*4;
    q.big_end=q.count1_end;
    while (q.big_end>=4) {
        bool small=true;
        for (int i=q.big_end-4; i<q.big_end; ++i)
            small=small && std::abs(q.samples[static_cast<std::size_t>(i)])<=1;
        if (!small) break;
        q.big_end-=4;
    }
    int quad_costs[2]{0,0};
    for (int i=q.big_end; i<q.count1_end; i+=4) {
        int symbol=0, signs=0;
        for (int k=0; k<4; ++k) {
            const int nonzero=q.samples[static_cast<std::size_t>(i+k)] != 0;
            symbol=(symbol<<1)|nonzero;
            signs+=nonzero;
        }
        quad_costs[0]+=detail::kCount1_32[static_cast<std::size_t>(symbol)].length+signs;
        quad_costs[1]+=detail::kCount1_33[static_cast<std::size_t>(symbol)].length+signs;
    }
    q.count1_table=quad_costs[1]<quad_costs[0] ? 1 : 0;
    std::array<std::array<int,289>,32> prefix{};
    for (int table=0; table<32; ++table) {
        if (table == 4 || table == 14) continue;
        for (int pair=0; pair<q.big_end/2; ++pair)
            prefix[static_cast<std::size_t>(table)][static_cast<std::size_t>(pair+1)]=
                prefix[static_cast<std::size_t>(table)][static_cast<std::size_t>(pair)] +
                pair_cost(q.samples[static_cast<std::size_t>(2*pair)],q.samples[static_cast<std::size_t>(2*pair+1)],table);
    }
    // A suffix region is queried repeatedly for different legal region splits.
    // Cache exact integer minima; retain ascending codebook order and strict ties.
    std::array<std::pair<int,int>,289> suffix_choices{};
    std::array<bool,289> suffix_known{};
    auto choose=[&](int first, int last_pair) {
        int best_table=0, best_cost=kImpossible;
        if (first == last_pair) return std::pair<int,int>{0,0};
        const bool suffix=last_pair == q.big_end/2;
        if (suffix && suffix_known[static_cast<std::size_t>(first)]) return suffix_choices[static_cast<std::size_t>(first)];
        for (int t=0; t<32; ++t) {
            if (t==4 || t==14) continue;
            const int cost=prefix[static_cast<std::size_t>(t)][static_cast<std::size_t>(last_pair)]-
                prefix[static_cast<std::size_t>(t)][static_cast<std::size_t>(first)];
            if (cost<best_cost) { best_table=t; best_cost=cost; }
        }
        const auto result=std::pair<int,int>{best_table,best_cost};
        if (suffix) {
            suffix_known[static_cast<std::size_t>(first)]=true;
            suffix_choices[static_cast<std::size_t>(first)]=result;
        }
        return result;
    };
    int best=kImpossible;
    if (q.type != BlockType::Normal) {
        const int first_end=std::min(36,q.big_end);
        const auto a=choose(0,first_end/2), b=choose(first_end/2,q.big_end/2);
        best=a.second+b.second;
        q.tables={a.first,b.first,0};
        q.region_ends={first_end,q.big_end,q.big_end};
    } else {
        const auto& bounds=sample_rate == 44100 ? kLong44100 : kLong48000;
        for (int c0=0; c0<16; ++c0) {
            const int first_end=std::min(bounds[static_cast<std::size_t>(c0+1)],q.big_end);
            const auto a=choose(0,first_end/2);
            for (int c1=0; c1<8 && c0+c1+2<=22; ++c1) {
                const int second_end=std::min(bounds[static_cast<std::size_t>(c0+c1+2)],q.big_end);
                const auto b=choose(first_end/2,second_end/2), c=choose(second_end/2,q.big_end/2);
                if (a.second+b.second+c.second<best) {
                    best=a.second+b.second+c.second;
                    q.region0_count=c0; q.region1_count=c1;
                    q.tables={a.first,b.first,c.first};
                    q.region_ends={first_end,second_end,q.big_end};
                }
            }
        }
    }
    q.bits=q.scale_bits+best+quad_costs[q.count1_table];
}

void choose_scale_compress(Quantized& q) {
    const bool short_block=q.type == BlockType::Short;
    const int split=short_block ? 18 : 11;
    const int end=short_block ? 36 : 21;
    int maximum1=0, maximum2=0;
    for (int i=0; i<split; ++i) maximum1=std::max(maximum1,q.scales[static_cast<std::size_t>(i)]);
    for (int i=split; i<end; ++i) maximum2=std::max(maximum2,q.scales[static_cast<std::size_t>(i)]);
    q.scale_bits=kImpossible;
    for (int index=0; index<16; ++index) {
        if (maximum1 >= (1<<kSlen1[static_cast<std::size_t>(index)]) || maximum2 >= (1<<kSlen2[static_cast<std::size_t>(index)])) continue;
        const int cost=split*kSlen1[static_cast<std::size_t>(index)]+(end-split)*kSlen2[static_cast<std::size_t>(index)];
        if (cost<q.scale_bits) { q.compress=index; q.scale_bits=cost; }
    }
    if (q.scale_bits == kImpossible) throw std::logic_error("MPEG scalefactor overflow");
}

Quantized evaluate(const Prepared& p, int sample_rate, int gain, const std::array<int,39>& scales) {
    Quantized q;
    q.type=p.type; q.gain=gain; q.scales=scales;
    choose_scale_compress(q);
    const auto& pow43=powers43();
    q.score=0;
    for (int band=0; band<p.band_count; ++band) {
        const auto& b=p.bands[static_cast<std::size_t>(band)];
        const int sf=scales[static_cast<std::size_t>(b.scale_index)];
        const double step=std::exp2(static_cast<double>(gain-210)*0.25-static_cast<double>(sf)*0.5);
        const double inverse75=std::exp2(-static_cast<double>(gain-210)*0.1875+static_cast<double>(sf)*0.375);
        double noise=0;
        for (int i=b.first; i<b.last; ++i) {
            const double x=p.values[static_cast<std::size_t>(i)];
            const double estimate=p.powers75[static_cast<std::size_t>(i)]*inverse75;
            if (estimate>static_cast<double>(kMaxQuantized)+0.5) { q.bits=kImpossible; return q; }
            int magnitude=static_cast<int>(estimate);
            if (magnitude<kMaxQuantized && std::abs(x)/step >
                (pow43[static_cast<std::size_t>(magnitude)]+pow43[static_cast<std::size_t>(magnitude+1)])*0.5) ++magnitude;
            q.samples[static_cast<std::size_t>(i)]=x<0 ? -magnitude : magnitude;
            const double error=std::abs(x)-pow43[static_cast<std::size_t>(magnitude)]*step;
            noise+=error*error;
        }
        const double ratio=noise/b.threshold;
        q.noise_ratios[static_cast<std::size_t>(band)]=ratio;
        q.score+=std::log1p(ratio);
    }
    choose_codebooks(q,sample_rate);
    return q;
}

Quantized fit(const Prepared& p, int sample_rate, int budget, const std::array<int,39>& scales) {
    int low=0, high=255;
    while (low<high) {
        const int middle=low+(high-low)/2;
        const auto trial=evaluate(p,sample_rate,middle,scales);
        if (trial.bits<=budget) high=middle;
        else low=middle+1;
    }
    auto q=evaluate(p,sample_rate,low,scales);
    if (q.bits>budget) throw std::runtime_error("spectral quantization cannot fit the MPEG bit budget");
    // Huffman sizes are not strictly monotonic. Check nearby finer gains, whose
    // codebook changes can save bits, instead of relying solely on bisection.
    for (int finer=std::max(0,low-2); finer<low; ++finer) {
        auto trial=evaluate(p,sample_rate,finer,scales);
        if (trial.bits<=budget && trial.score<q.score) q=std::move(trial);
    }
    return q;
}

Quantized quantize(const Spectrum& spectrum, int sample_rate, int budget) {
    const auto p=prepare(spectrum,sample_rate);
    std::array<int,39> scales{};
    auto best=fit(p,sample_rate,budget,scales);
    auto current=best;
    // Distortion-control outer loop. Selectively refine the bands whose actual
    // reconstruction noise most exceeds the psychoacoustic threshold, then
    // rerun rate control. Retain the lowest normalized noise under the budget.
    for (int iteration=0; iteration<4; ++iteration) {
        std::array<int,39> order{};
        for (int i=0; i<p.band_count; ++i) order[static_cast<std::size_t>(i)]=i;
        std::sort(order.begin(),order.begin()+p.band_count,[&current](int a,int b) {
            return current.noise_ratios[static_cast<std::size_t>(a)]>current.noise_ratios[static_cast<std::size_t>(b)];
        });
        int changes=0;
        for (int position=0; position<p.band_count && changes<3; ++position) {
            const int band=order[static_cast<std::size_t>(position)];
            if (current.noise_ratios[static_cast<std::size_t>(band)]<=1) break;
            const int sf=p.bands[static_cast<std::size_t>(band)].scale_index;
            const int split=p.type == BlockType::Short ? 18 : 11;
            const int end=p.type == BlockType::Short ? 36 : 21;
            if (sf>=end || scales[static_cast<std::size_t>(sf)] >= (sf<split ? 15 : 7)) continue;
            ++scales[static_cast<std::size_t>(sf)]; ++changes;
        }
        if (!changes) break;
        current=fit(p,sample_rate,budget,scales);
        if (current.score<best.score) best=current;
    }
    return best;
}

void write_pair(BitWriter& out, int x, int y, int table) {
    const auto& t=detail::kHuffmanTables[static_cast<std::size_t>(table)];
    const int ax=std::abs(x), ay=std::abs(y);
    const int cx=t.linbits ? std::min(ax,15) : ax, cy=t.linbits ? std::min(ay,15) : ay;
    if (!t.codes || cx>=t.dimension || cy>=t.dimension) throw std::logic_error("MPEG Huffman symbol overflow");
    const auto code=t.codes[static_cast<std::size_t>(cx*t.dimension+cy)];
    out.put(code.code,code.length);
    if (t.linbits && ax>=15) out.put(static_cast<std::uint32_t>(ax-15),t.linbits);
    if (ax) out.put(x<0 ? 1U : 0U,1);
    if (t.linbits && ay>=15) out.put(static_cast<std::uint32_t>(ay-15),t.linbits);
    if (ay) out.put(y<0 ? 1U : 0U,1);
}

BitWriter write_main_data(const Quantized& q) {
    BitWriter result(static_cast<std::size_t>((q.bits+7)/8));
    const int split=q.type == BlockType::Short ? 18 : 11;
    const int end=q.type == BlockType::Short ? 36 : 21;
    for (int i=0; i<end; ++i)
        result.put(static_cast<std::uint32_t>(q.scales[static_cast<std::size_t>(i)]),
            i<split ? kSlen1[static_cast<std::size_t>(q.compress)] : kSlen2[static_cast<std::size_t>(q.compress)]);
    int first=0;
    for (int region=0; region<3; ++region) {
        for (int i=first; i<q.region_ends[static_cast<std::size_t>(region)]; i+=2)
            write_pair(result,q.samples[static_cast<std::size_t>(i)],q.samples[static_cast<std::size_t>(i+1)],q.tables[static_cast<std::size_t>(region)]);
        first=q.region_ends[static_cast<std::size_t>(region)];
    }
    for (int i=q.big_end; i<q.count1_end; i+=4) {
        int symbol=0;
        for (int k=0; k<4; ++k) symbol=(symbol<<1)|(q.samples[static_cast<std::size_t>(i+k)] != 0);
        const auto code=q.count1_table ? detail::kCount1_33[static_cast<std::size_t>(symbol)] : detail::kCount1_32[static_cast<std::size_t>(symbol)];
        result.put(code.code,code.length);
        for (int k=0; k<4; ++k) if (q.samples[static_cast<std::size_t>(i+k)]) result.put(q.samples[static_cast<std::size_t>(i+k)]<0 ? 1U : 0U,1);
    }
    if (result.bits() != static_cast<std::size_t>(q.bits)) throw std::logic_error("MPEG Huffman bit accounting mismatch");
    return result;
}

void write_granule_side(BitWriter& out, const Quantized& q) {
    out.put(static_cast<std::uint32_t>(q.bits),12);
    out.put(static_cast<std::uint32_t>(q.big_end/2),9);
    out.put(static_cast<std::uint32_t>(q.gain),8);
    out.put(static_cast<std::uint32_t>(q.compress),4);
    out.put(q.type == BlockType::Normal ? 0U : 1U,1);
    if (q.type != BlockType::Normal) {
        out.put(static_cast<std::uint32_t>(q.type),2);
        out.put(0,1); // pure block: mixed_block_flag
        out.put(static_cast<std::uint32_t>(q.tables[0]),5);
        out.put(static_cast<std::uint32_t>(q.tables[1]),5);
        out.put(0,9); // subblock gains; scaling is encoded with scalefactors
    } else {
        for (const int table:q.tables) out.put(static_cast<std::uint32_t>(table),5);
        out.put(static_cast<std::uint32_t>(q.region0_count),4);
        out.put(static_cast<std::uint32_t>(q.region1_count),3);
    }
    out.put(0,1); // preflag
    out.put(0,1); // scalefac_scale: half-power-of-two attenuation
    out.put(static_cast<std::uint32_t>(q.count1_table),1);
}

} // namespace

Spectrum reconstruct(const Quantized& q,int rate) {
    Spectrum result;result.block_type=q.type;const auto& powers=powers43();
    auto value=[&](int index,int band){const int v=q.samples[static_cast<std::size_t>(index)];return (v<0 ? -1.0 : 1.0)*powers[static_cast<std::size_t>(std::abs(v))]*std::exp2((q.gain-210)*.25-q.scales[static_cast<std::size_t>(band)]*.5);};
    if(q.type==BlockType::Short) {
        const auto& bounds=rate==44100 ? kShort44100 : kShort48000;int index=0;
        for(int band=0;band<13;++band)for(int w=0;w<3;++w)for(int f=bounds[static_cast<std::size_t>(band)];f<bounds[static_cast<std::size_t>(band+1)];++f)
            result.values[static_cast<std::size_t>((f/6)*18+(f%6)*3+w)]=value(index++,band*3+w);
    } else {
        const auto& bounds=rate==44100 ? kLong44100 : kLong48000;
        for(int band=0;band<22;++band)for(int i=bounds[static_cast<std::size_t>(band)];i<bounds[static_cast<std::size_t>(band+1)];++i)result.values[static_cast<std::size_t>(i)]=value(i,band);
    }
    return result;
}

class MpegWriter::Impl {
public:
    Impl(int rate,int channel_count,int bitrate,Sink destination)
        : sample_rate(rate), channels(channel_count), bitrate_kbps(bitrate), sink(std::move(destination)) {
        if ((rate != 44100 && rate != 48000) || (channels != 1 && channels != 2) ||
            (bitrate != 128 && bitrate != 192 && bitrate != 256 && bitrate != 320) || !sink)
            throw std::invalid_argument("invalid MPEG-1 Layer III writer configuration");
    }
    struct Frame {
        std::uint64_t start=0;
        std::vector<std::uint8_t> prefix, payload;
    };
    int sample_rate,channels,bitrate_kbps;
    Sink sink;
    std::deque<Frame> frames;
    std::uint64_t slots_end=0,data_end=0,count=0,bytes=0,references=0;
    std::size_t peak_reservoir=0;
    std::uint64_t padding_accumulator=0;
    bool finished=false,failed=false;
    using Input=std::array<std::array<Spectrum,2>,2>;
    std::deque<Input> pending;
    std::deque<double> pending_gains;
    std::array<SynthesisMonitor,2> monitors;
    double last_peak=0,maximum_peak=0,minimum_gain=1;
    std::uint64_t protected_count=0;

    static Input scaled(Input input,double gain) {
        if(gain!=1)for(auto& granule:input)for(auto& s:granule) {
            for(auto& v:s.values)v*=gain;
            for(auto& v:s.masking)v*=gain*gain;
        }
        return input;
    }
    void protect_front() {
        // Check the current frame plus one real frame of lookahead. A trial
        // never emits bytes or mutates the committed overlap/reservoir state.
        constexpr double ceiling=.995;
        double current_gain=1,next_gain=1;bool accepted=false;
        auto check=[&](double a,double b) {
            auto trial=*this;trial.pending.clear();trial.sink=[](const std::uint8_t*,std::size_t){};
            trial.encode(scaled(pending.front(),a));double peak=trial.last_peak;
            if(pending.size()>1)trial.encode(scaled(pending[1],b));else trial.encode(Input{});
            return std::max(peak,trial.last_peak);
        };
        double peak=check(1,1);
        if(peak<=ceiling)accepted=true;
        double gain=1;
        for(int attempt=0;!accepted && attempt<18;++attempt) {
            gain*=std::clamp(ceiling/peak-.001,.7,.995);
            // Independent adjacent gains avoid destroying useful overlap
            // cancellation while correcting an overload in the next frame.
            for(const auto pair:std::array<std::pair<double,double>,3>{{{gain,1},{1,gain},{gain,gain}}}) {
                const double candidate=check(pair.first,pair.second);
                if(candidate<=ceiling) {current_gain=pair.first;next_gain=pair.second;accepted=true;break;}
                if(pair.first==pair.second)peak=candidate;
            }
        }
        if(!accepted) {
            constexpr std::array<double,16> gains{1,.999,.997,.995,.99,.98,.97,.95,.925,.9,.85,.8,.75,.7,.6,.5};
            for(double a:gains) {
                for(double b:gains)if(check(a,b)<=ceiling){current_gain=a;next_gain=b;accepted=true;break;}
                if(accepted)break;
            }
        }
        if(!accepted)throw std::runtime_error("Peak-constrained MP3 reconstruction did not converge");
        if(current_gain!=1 || next_gain!=1) {
            pending.front()=scaled(std::move(pending.front()),current_gain);
            if(pending.size()>1)pending[1]=scaled(std::move(pending[1]),next_gain);
            pending_gains.front()*=current_gain;
            if(pending.size()>1)pending_gains[1]*=next_gain;
        }
        minimum_gain=std::min(minimum_gain,pending_gains.front());
        if(pending_gains.front()!=1)++protected_count;
        encode(pending.front());pending.pop_front();pending_gains.pop_front();
    }
    void write(const Input& input) {
        if(count>=std::numeric_limits<std::uint64_t>::max()-pending.size())throw std::overflow_error("MPEG frame counter overflow");
        pending.push_back(input);pending_gains.push_back(1);if(pending.size()>=2)protect_front();
    }

    void emit_ready(bool all=false) {
        while (!frames.empty()) {
            const auto& frame=frames.front();
            if (!all && frame.start+frame.payload.size()>data_end) break;
            // A single bounded write per MPEG frame reduces JNI crossings and
            // permits an OutputStream error to terminate the session cleanly.
            std::vector<std::uint8_t> encoded;
            encoded.reserve(frame.prefix.size()+frame.payload.size());
            encoded.insert(encoded.end(),frame.prefix.begin(),frame.prefix.end());
            encoded.insert(encoded.end(),frame.payload.begin(),frame.payload.end());
            sink(encoded.data(),encoded.size());
            if (bytes>std::numeric_limits<std::uint64_t>::max()-encoded.size()) throw std::overflow_error("MPEG output byte count overflow");
            bytes+=encoded.size();
            frames.pop_front();
        }
    }

    void store_data(const std::vector<std::uint8_t>& main_data) {
        std::uint64_t position=data_end;
        std::size_t copied=0;
        for (auto& frame:frames) {
            if (position>=frame.start+frame.payload.size()) continue;
            if (position<frame.start) throw std::logic_error("MPEG reservoir has an unwritten gap");
            const std::size_t offset=static_cast<std::size_t>(position-frame.start);
            const std::size_t length=std::min(main_data.size()-copied,frame.payload.size()-offset);
            std::copy_n(main_data.begin()+static_cast<std::ptrdiff_t>(copied),length,frame.payload.begin()+static_cast<std::ptrdiff_t>(offset));
            copied+=length; position+=length;
            if (copied == main_data.size()) break;
        }
        if (copied != main_data.size()) throw std::logic_error("MPEG reservoir exceeds available frame storage");
        data_end=position;
    }

    void encode(const std::array<std::array<Spectrum,2>,2>& input) {
        if (finished || failed) throw std::logic_error("MPEG writer is closed");
        if (count == std::numeric_limits<std::uint64_t>::max()) throw std::overflow_error("MPEG frame counter overflow");
        const std::uint64_t numerator=144000ULL*static_cast<std::uint64_t>(bitrate_kbps);
        const std::size_t base=static_cast<std::size_t>(numerator/static_cast<std::uint64_t>(sample_rate));
        padding_accumulator+=numerator%static_cast<std::uint64_t>(sample_rate);
        const bool padding=padding_accumulator>=static_cast<std::uint64_t>(sample_rate);
        if (padding) padding_accumulator-=static_cast<std::uint64_t>(sample_rate);
        const std::size_t frame_size=base+(padding ? 1U : 0U);
        const std::size_t side_size=channels == 1 ? 17U : 32U;
        const std::size_t capacity=frame_size-4U-side_size;
        if (slots_end>std::numeric_limits<std::uint64_t>::max()-capacity) throw std::overflow_error("MPEG main-data offset overflow");
        if (slots_end<data_end) throw std::logic_error("invalid MPEG reservoir cursor");
        // Drop old unused capacity as ancillary zero bytes before it can exceed
        // main_data_begin's normative 9-bit range. Queued payloads start as zero.
        if (slots_end-data_end>511U) data_end=slots_end-511U;
        const std::size_t reservoir=static_cast<std::size_t>(slots_end-data_end);
        peak_reservoir=std::max(peak_reservoir,reservoir);
        if (reservoir) ++references;
        // All 576 coefficients must be exactly zero to reserve no audio bits.
        // This is not an amplitude gate: any nonzero value, however quiet,
        // remains an active part. Inspect the entire frame before allocation
        // so later silent granules do not strand bits needed by an earlier one.
        // Only this inexpensive scan is added; quantization still runs once
        // per part, with its existing bounded rate/distortion loops.
        std::array<std::array<bool,2>,2> active{};
        int active_parts=0;
        for (int granule=0; granule<2; ++granule) {
            for (int channel=0; channel<channels; ++channel) {
                const auto& spectrum=input[static_cast<std::size_t>(granule)][static_cast<std::size_t>(channel)];
                const bool nonzero=std::any_of(spectrum.values.begin(),spectrum.values.end(),[](double value){return value != 0.0;});
                active[static_cast<std::size_t>(granule)][static_cast<std::size_t>(channel)]=nonzero;
                active_parts+=nonzero ? 1 : 0;
            }
        }
        int remaining=static_cast<int>((capacity+reservoir)*8U)-7;
        std::array<std::array<Quantized,2>,2> quantized{};
        BitWriter main(capacity+reservoir);
        for (int granule=0; granule<2; ++granule) {
            for (int channel=0; channel<channels; ++channel) {
                const bool nonzero=active[static_cast<std::size_t>(granule)][static_cast<std::size_t>(channel)];
                const int budget=nonzero ? std::min(4095,remaining/active_parts) : 0;
                auto q=quantize(input[static_cast<std::size_t>(granule)][static_cast<std::size_t>(channel)],sample_rate,budget);
                active_parts-=nonzero ? 1 : 0;
                remaining-=q.bits;
                main.append(write_main_data(q));
                quantized[static_cast<std::size_t>(granule)][static_cast<std::size_t>(channel)]=std::move(q);
            }
        }
        if (main.bytes().size()>capacity+reservoir) throw std::logic_error("MPEG bit budget overflow");
        last_peak=0;
        for(std::size_t g=0;g<2;++g)for(int c=0;c<channels;++c)
            last_peak=std::max(last_peak,monitors[static_cast<std::size_t>(c)].peak(reconstruct(quantized[g][static_cast<std::size_t>(c)],sample_rate)));
        maximum_peak=std::max(maximum_peak,last_peak);
        BitWriter header;
        header.put(0x7ff,11); header.put(3,2); header.put(1,2); header.put(1,1);
        const int bitrate_index=bitrate_kbps == 128 ? 9 : bitrate_kbps == 192 ? 11 : bitrate_kbps == 256 ? 13 : 14;
        header.put(static_cast<std::uint32_t>(bitrate_index),4);
        header.put(sample_rate == 44100 ? 0U : 1U,2);
        header.put(padding ? 1U : 0U,1); header.put(0,1);
        header.put(channels == 1 ? 3U : 0U,2); header.put(0,2);
        header.put(0,1); header.put(0,1); header.put(0,2);
        BitWriter side;
        side.put(static_cast<std::uint32_t>(reservoir),9);
        side.put(0,channels == 1 ? 5 : 3);
        side.put(0,channels*4); // scfsi: each granule has independent scalefactors
        for (int granule=0; granule<2; ++granule)
            for (int channel=0; channel<channels; ++channel)
                write_granule_side(side,quantized[static_cast<std::size_t>(granule)][static_cast<std::size_t>(channel)]);
        if (header.bits()!=32U || side.bits()!=side_size*8U) throw std::logic_error("MPEG side information size mismatch");
        Frame frame;
        frame.start=slots_end;
        frame.prefix=header.bytes();
        frame.prefix.insert(frame.prefix.end(),side.bytes().begin(),side.bytes().end());
        frame.payload.resize(capacity,0);
        frames.push_back(std::move(frame));
        slots_end+=capacity;
        store_data(main.bytes());
        ++count;
        emit_ready();
    }
};

MpegWriter::MpegWriter(int sample_rate,int channels,int bitrate_kbps,Sink sink)
    : impl_(std::make_unique<Impl>(sample_rate,channels,bitrate_kbps,std::move(sink))) {}
MpegWriter::~MpegWriter()=default;
void MpegWriter::write_frame(const std::array<std::array<Spectrum,2>,2>& granules) {
    try { impl_->write(granules); }
    catch (...) { impl_->failed=true; throw; }
}
void MpegWriter::finish() {
    if (impl_->failed) throw std::logic_error("MPEG writer failed");
    if (impl_->finished) return;
    try { while(!impl_->pending.empty())impl_->protect_front();impl_->emit_ready(true); impl_->finished=true; }
    catch (...) { impl_->failed=true; throw; }
}
std::uint64_t MpegWriter::frame_count() const noexcept { return impl_->count+impl_->pending.size(); }
std::uint64_t MpegWriter::output_bytes() const noexcept { return impl_->bytes; }
std::uint64_t MpegWriter::reservoir_references() const noexcept { return impl_->references; }
std::size_t MpegWriter::peak_reservoir_bytes() const noexcept { return impl_->peak_reservoir; }
double MpegWriter::reconstruction_peak() const noexcept {return impl_->maximum_peak;}
std::uint64_t MpegWriter::protected_frames() const noexcept {return impl_->protected_count;}
double MpegWriter::minimum_peak_gain() const noexcept {return impl_->minimum_gain;}

} // namespace uwdev::mp3codec
