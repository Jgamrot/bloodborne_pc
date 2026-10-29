/* BB_AUDIO_CHANNELS (GitHub issue #195): a 7.1 port folded to the chosen
 * stereo keeps the centre (dialogue) in both fronts. SDL's dummy driver:
 * nothing reaches a playback device. */
#include "../src/runtime_audio.c"
#include <assert.h>

int runtime_file_translate(const char *guest, char *out, size_t size) { (void)guest; (void)out; (void)size; return -1; }
void compat_sleep_ns(uint64_t ns) { (void)ns; }
uintptr_t runtime_lookup(const RuntimeExport *table, size_t count, const char *nid) {
    (void)table; (void)count; (void)nid; return 0;
}

#ifdef _WIN32
#define set_env(name,value) _putenv_s(name,value)
#else
#define set_env(name,value) setenv(name,value,1)
#endif
static int close_to(float a, float b) { return a-b<1e-4f && b-a<1e-4f; }

int main(int argc, char **argv) {
    assert(argc==2);
    assert(set_env("SDL_AUDIODRIVER","dummy")==0);
    assert(set_env("BB_AUDIO","")==0);
    assert(set_env("BB_AUDIO_CHANNELS","2")==0);
    assert(set_env("BB_AUDIO_DUMP",argv[1])==0);
    assert(audio_init()==0);
    /* FLOAT_8CH (L R C LFE SL SR BL BR) and FLOAT_8CH_STD (L R C LFE BL BR SL SR). */
    for (int format=5;format<=7;format+=2) {
        int32_t port=audio_open(1,0,0,256,48000,(uint32_t)format);
        assert(port>=0 && ports[port&0xff].out_channels==2);
        static float frames[256*8];
        for (int f=0;f<256;++f) for (int c=0;c<8;++c) frames[f*8+c]=c==2 ? 0.5f : c==0 ? 0.25f : 0.f;
        assert(output_port(port,frames,0)==256*8);
        assert(audio_close(port)==0);
        char path[4096];
        assert(snprintf(path,sizeof(path),"%s.port0.8ch.f32",argv[1])<(int)sizeof(path));
        FILE *dump=fopen(path,"rb"); assert(dump);
        float stereo[256*2];
        assert(fread(stereo,sizeof(float),256*2,dump)==256*2);
        fclose(dump);
        for (int f=0;f<256;++f) {
            assert(close_to(stereo[f*2],0.25f+0.70710678f*0.5f));
            assert(close_to(stereo[f*2+1],0.70710678f*0.5f));
        }
    }
    puts("AUDIO_CHANNELS_PASS stereo fold keeps the centre");
    SDL_QuitSubSystem(SDL_INIT_AUDIO);
    return 0;
}
