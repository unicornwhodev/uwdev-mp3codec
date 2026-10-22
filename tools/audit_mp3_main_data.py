# SPDX-License-Identifier: MIT
"""Additional strict Layer III payload checks for the uwdev MPEG-1 profile.

This is a test-side parser, not an ISO conformance certification. Codeword
numbers share the attributed pinned numerical tables; FFmpeg/mpg123/Android
remain the independent decoder checks. No production encoder is called here.
"""
import os
from pathlib import Path
import hashlib,json,re,sys
ROOT=Path(__file__).resolve().parents[1];BASE=Path(os.environ.get('UWDEV_QUALIFICATION_ROOT',ROOT/'build/qualification'))
class Invalid(ValueError):pass
def require(condition,message):
    if not condition:raise Invalid(message)
class Reader:
    def __init__(self,data,start=0,limit=None):self.data=data;self.pos=start;self.limit=len(data)*8 if limit is None else limit
    def get(self,n):
        require(n>=0 and self.pos+n<=self.limit,'bit budget overrun')
        if n==0:return 0
        offset=self.pos%8;first=self.pos//8;count=(offset+n+7)//8
        value=int.from_bytes(self.data[first:first+count],'big')
        self.pos+=n
        return (value>>(count*8-offset-n))&((1<<n)-1)
def tables():
    text=(ROOT/'encoder-android/src/main/cpp/codec/huffman_tables.hpp').read_text()
    codes={name:[(int(a),int(b)) for a,b in re.findall(r'\{(\d+)U,\s*(\d+)\}',body)]
        for name,body in re.findall(r'\b(kHuff\d+|kCount1_\d+)\s*=\s*\{\{(.*?)\}\};',text,re.S)}
    descriptors=re.findall(r'\{(kHuff\d+)\.data\(\),\s*(\d+),\s*(\d+)\}|\{nullptr, 0, 0\}',text)
    def book(name):return {(length,code):i for i,(code,length) in enumerate(codes[name])}
    pair=[]
    for name,dim,lin in descriptors:pair.append((book(name),int(dim),int(lin)) if name else None)
    require(len(pair)==32,'codebook descriptor inventory')
    return pair,[book('kCount1_32'),book('kCount1_33')]
PAIR,QUAD=tables()
LONG={44100:[0,4,8,12,16,20,24,30,36,44,52,62,74,90,110,134,162,196,238,288,342,418,576],
      48000:[0,4,8,12,16,20,24,30,36,42,50,60,72,88,106,128,156,190,230,276,330,384,576]}
SLEN1=[0,0,0,0,3,1,1,1,2,2,2,3,3,3,4,4];SLEN2=[0,1,2,3,0,1,2,3,1,2,3,1,2,3,2,3]
def symbol(reader,book):
    if (0,0) in book:return book[(0,0)]
    code=0
    for length in range(1,20):
        code=(code<<1)|reader.get(1)
        if (length,code) in book:return book[(length,code)]
    raise Invalid('invalid Huffman prefix')
def inspect(data):
    pos=0;frames=[];payload=bytearray();previous_end=0;states=[0,0]
    for_frame=[];peak=0;total_pairs=0;total_quads=0;used_tables=set();used_blocks=set();parts=0
    while pos<len(data):
        require(pos+4<=len(data),'truncated header');h=int.from_bytes(data[pos:pos+4],'big')
        require(h>>21==0x7ff and ((h>>19)&3)==3 and ((h>>17)&3)==1,'not raw MPEG-1 Layer III')
        require((h>>16)&1==1,'CRC profile mismatch')
        rate=[44100,48000,32000,0][(h>>10)&3];require(rate in LONG,'unsupported uwdev sample rate')
        kbps=[0,32,40,48,56,64,80,96,112,128,160,192,224,256,320,0][(h>>12)&15]
        require(kbps in (128,192,256,320),'CBR profile mismatch')
        channel_mode=(h>>6)&3;require(channel_mode in (0,3),'channel mode profile mismatch');channels=1 if channel_mode==3 else 2
        length=144000*kbps//rate+((h>>9)&1);require(pos+length<=len(data),'truncated frame')
        side_length=17 if channels==1 else 32;side=Reader(data,(pos+4)*8,(pos+4+side_length)*8)
        back=side.get(9);side.get(5 if channels==1 else 3)
        require(all(side.get(4)==0 for _ in range(channels)),'unexpected scfsi in uwdev profile')
        start=(len(payload)-back)*8;require(start>=previous_end and back<=511,'invalid reservoir reference')
        info=[]
        for gr in range(2):
            for channel in range(channels):
                offset=side.pos;part=side.get(12);big=side.get(9);gain=side.get(8);compress=side.get(4);switched=side.get(1)
                require(big<=288,'big_values exceeds 288')
                if switched:
                    block=side.get(2);mixed=side.get(1);require(block in (1,2,3) and mixed==0,'invalid switched pure block')
                    books=[side.get(5),side.get(5),0];require(all(side.get(3)==0 for _ in range(3)),'unexpected subblock gain')
                    ends=[36,576,576]
                else:
                    block=0;books=[side.get(5) for _ in range(3)];r0=side.get(4);r1=side.get(3)
                    require(r0+r1+2<23,'scale-factor region overflow');ends=[LONG[rate][r0+1],LONG[rate][r0+r1+2],576]
                require(side.get(1)==0 and side.get(1)==0,'unexpected preflag/scalefac scale')
                count1=side.get(1);require(all(b not in (4,14) for b in books),'forbidden codebook')
                require(block in {0:{0,1},1:{2},2:{2,3},3:{0,1}}[states[channel]],'illegal hybrid window transition')
                states[channel]=block;used_blocks.add(block)
                info.append((part,big,compress,block,books,ends,count1,gr,channel,offset))
        require(side.pos==side.limit,'side-info length mismatch')
        payload.extend(data[pos+4+side_length:pos+length]);cursor=start
        for part,big,compress,block,books,ends,count1,gr,channel,offset in info:
            try:
                reader=Reader(payload,cursor,cursor+part);require(reader.limit<=len(payload)*8,'main-data budget overrun')
                scale_bits=(18*SLEN1[compress]+18*SLEN2[compress]) if block==2 else (11*SLEN1[compress]+10*SLEN2[compress])
                reader.get(scale_bits)
                for pair in range(big):
                    line=2*pair;region=0 if line<ends[0] else (1 if line<ends[1] else 2);index=books[region]
                    book,dimension,linbits=PAIR[index];used_tables.add(index);value=symbol(reader,book)
                    for v in [value//dimension,value%dimension]:
                        if v==15 and linbits:v+=reader.get(linbits)
                        require(v<=8206,'quantized magnitude overflow');peak=max(peak,v)
                        if v:reader.get(1)
                line=2*big;quads=0
                while reader.pos<reader.limit:
                    require(line+4<=576,'count1 exceeds 576 spectral lines')
                    value=symbol(reader,QUAD[count1]);reader.get(value.bit_count());line+=4;quads+=1
                require(reader.pos==reader.limit,'part2_3_length consumption mismatch')
                total_pairs+=big;total_quads+=quads;parts+=1;cursor+=part
                if part and not for_frame:for_frame=[offset,part]
            except Invalid as e:raise Invalid(f'frame={len(frames)} granule={gr} channel={channel} bit={reader.pos}: {e}') from e
        previous_end=cursor;frames.append(length);pos+=length
    require(frames,'empty stream');require(all(s==0 for s in states[:channels]),'hybrid filterbank not drained to normal blocks')
    return {'frames':len(frames),'granule_channels':parts,'huffman_pairs':total_pairs,'count1_quads':total_quads,
        'maximum_quantized_magnitude':peak,'codebooks':sorted(used_tables),'block_types':sorted(used_blocks),'first_active_side_field':for_frame}
def patch_field(data,offset,width,value):
    result=bytearray(data)
    for i in range(width):
        p=offset+i;mask=1<<(7-p%8);result[p//8]=(result[p//8]&~mask)|(((value>>(width-i-1))&1)<<(7-p%8))
    return bytes(result)
def main():
    files=sorted((BASE/'oppo-candidate').glob('*.mp3'))+sorted((BASE/'candidate-native').glob('*.mp3'))+sorted((BASE/'candidate-edges').glob('*.mp3'))
    require(len(files)==528,f'expected 60+264+204 MP3s, found {len(files)}')
    rows=[]
    for path in files:
        data=path.read_bytes();row={'file':str(path.relative_to(BASE)).replace('\\','/'),'sha256':hashlib.sha256(data).hexdigest()}
        try:row.update(inspect(data));row['status']='PASS'
        except Exception as error:row.update(status='FAIL',error=str(error))
        rows.append(row)
        if len(rows)%30==0:print('Audited',len(rows),'/',len(files),flush=True)
    sample=next(p for p in files if p.name=='01_piano_192.mp3');data=sample.read_bytes();active=inspect(data)['first_active_side_field'][0]
    controls={
        'bad_sync':bytes([data[0]^0x80])+data[1:],
        'truncated_last_frame':data[:-1],
        'reservoir_before_stream_start':patch_field(data,32,9,511),
        'big_values_overflow':patch_field(data,active+12,9,511),
        'zero_bit_budget_for_active_granule':patch_field(data,active,12,0),
    };negative=[]
    for name,value in controls.items():
        try:inspect(value);negative.append({'case':name,'rejected':False})
        except Invalid as error:negative.append({'case':name,'rejected':True,'reason':str(error)})
    report={'scope':'uwdev MPEG-1 pure stereo/mono profile; additional strict payload audit, not official ISO certification',
        'shared_numerical_table_limitation':'Codeword data shares the reviewed pinned tables; independent decoder evidence is supplied separately.',
        'rows':rows,'passed':sum(r['status']=='PASS' for r in rows),'total':len(rows),'negative_controls':negative}
    (BASE/'mp3-main-data-audit.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({'passed':report['passed'],'total':report['total'],'negative_controls':negative,'failures':[r for r in rows if r['status']!='PASS'][:5]},indent=2))
    return 0 if report['passed']==report['total'] and all(r['rejected'] for r in negative) else 1
if __name__=='__main__':raise SystemExit(main())
