#define _GNU_SOURCE
#include <assert.h>
#include <unistd.h>
#ifdef _WIN32
#include <windows.h>
#endif
#include "../src/runtime_pad.c"

#undef assert
#define assert(condition) do { if (!(condition)) { \
    fprintf(stderr,"FAIL: %s:%d: %s\n",__FILE__,__LINE__,#condition); exit(1); \
} } while (0)

static int capture;
int bbgpu_overlay_captures_input(void) { return capture; }
uint32_t bbgpu_atlas_route_pad(uint32_t b, uint8_t lx, uint8_t ly, uint8_t rx, uint8_t ry) { (void)lx; (void)ly; (void)rx; (void)ry; return b; }
uint32_t bbgpu_mouse_wheel_take(void) { return 0; }
int bb_menu_pointer_owns_mouse(void) { return 0; }
void bb_menu_pointer_click(void) {}
void bb_menu_pointer_back(void) {}
uint32_t bb_menu_pointer_buttons(void) { return 0; }
void bb_mouse_camera_note_stick(uint8_t x, uint8_t y) { (void)x; (void)y; }
int bb_mouse_camera_stick_x(void) { return -1; }
void bb_bindings_load(const char *path) { (void)path; }
void bb_bindings_apply(const bool *keys, int nkeys, uint32_t mouse, BindOutput *out) {
    (void)keys; (void)nkeys; (void)mouse;
    if (out) memset(out, 0, sizeof(*out));
}
uintptr_t runtime_lookup(const RuntimeExport *table, size_t count, const char *name) {
    (void)table; (void)count; (void)name;
    return 0;
}

static void inject(const char *path, const char *tokens) {
    FILE *f=fopen(path,"w");
    assert(f);
    fputs(tokens,f);
    fclose(f);
    usleep(25000);
}

int main(void) {
    char path[512];
#ifdef _WIN32
    const DWORD dir_len=GetTempPathA(sizeof path,path);
    assert(dir_len>0 && dir_len+sizeof("bbport-pad-test-XXXXXX")<sizeof path);
    snprintf(path+dir_len,sizeof path-dir_len,"bbport-pad-test-XXXXXX");
#else
    snprintf(path,sizeof path,"/tmp/bbport-pad-test-XXXXXX");
#endif
    int fd=mkstemp(path);
    assert(fd>=0);
    close(fd);
#ifdef _WIN32
    assert(_putenv_s("BB_PAD_FILE",path)==0);
#else
    setenv("BB_PAD_FILE",path,1);
#endif
    SDL_SetHint(SDL_HINT_VIDEO_DRIVER,"dummy");
    /* Only the virtual test controller is a gamepad, whatever is plugged in. */
    SDL_SetHint(SDL_HINT_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT,"0x1d50/0x6189");
    assert(SDL_Init(SDL_INIT_VIDEO|SDL_INIT_GAMEPAD));
    assert(pad_init()==0 && pad_open(1,0,0,NULL)==1);
    PadData data;
    inject(path,"cross l3 touchpad_left");
    assert(pad_read_state(1,&data)==0);
    assert((data.buttons & (BTN_CROSS|BTN_L3|BTN_TOUCHPAD))==(BTN_CROSS|BTN_L3|BTN_TOUCHPAD));
    assert(data.touch_count==1 && data.touches[0].x==480 && data.touches[0].y==471);
    const uint8_t first_touch_id=data.touches[0].id;
    assert(first_touch_id!=0 && data.touch_held_time==0);
    usleep(25000);
    assert(pad_read_state(1,&data)==0 && data.touches[0].id==first_touch_id);
    assert(data.touch_held_time>=20000);
    inject(path,"touchpad_right");
    assert(pad_read_state(1,&data)==0 && data.touch_count==1 && data.touches[0].x==1440);
    assert(data.touches[0].id==first_touch_id);
    inject(path,"");
    assert(pad_read_state(1,&data)==0 && data.buttons==0 && data.touch_count==0 && data.touch_held_time==0);
    inject(path,"touchpad_left");
    assert(pad_read_state(1,&data)==0 && data.touches[0].id!=first_touch_id);
    inject(path,"");
    assert(pad_read_state(1,&data)==0 && data.touch_count==0);

    SDL_VirtualJoystickTouchpadDesc touch={.nfingers=2};
    SDL_VirtualJoystickDesc desc;
    SDL_INIT_INTERFACE(&desc);
    desc.type=SDL_JOYSTICK_TYPE_GAMEPAD;
    desc.naxes=SDL_GAMEPAD_AXIS_COUNT;
    desc.nbuttons=SDL_GAMEPAD_BUTTON_COUNT;
    desc.button_mask=(1u<<SDL_GAMEPAD_BUTTON_COUNT)-1;
    desc.axis_mask=(1u<<SDL_GAMEPAD_AXIS_COUNT)-1;
    desc.name="bbport test controller";
    desc.vendor_id=0x1d50;
    desc.product_id=0x6189;
    desc.ntouchpads=1;
    desc.touchpads=&touch;
    SDL_JoystickID id=SDL_AttachVirtualJoystick(&desc);
    assert(id!=0);
    SDL_Joystick *joystick=SDL_OpenJoystick(id);
    assert(joystick);
    assert(SDL_SetJoystickVirtualTouchpad(joystick,0,0,true,0.75f,0.5f,1.0f));
    assert(SDL_SetJoystickVirtualTouchpad(joystick,0,1,true,0.25f,1.0f,1.0f));
    assert(SDL_SetJoystickVirtualButton(joystick,SDL_GAMEPAD_BUTTON_TOUCHPAD,true));
    SDL_UpdateJoysticks();
    SDL_UpdateGamepads();
    assert(pad_read_state(1,&data)==0);
    assert(gamepad && data.touch_count==2 && (data.buttons & BTN_TOUCHPAD));
    assert(data.touches[0].x==1439 && data.touches[0].y==471 && data.touches[0].id!=0);
    assert(data.touches[1].x==480 && data.touches[1].y==942 && data.touches[1].id!=0);
    assert(data.touches[0].id!=data.touches[1].id);
    capture=1;
    assert(pad_read_state(1,&data)==0 && data.touch_count==0 && data.buttons==0);
    capture=0;
    assert(SDL_SetJoystickVirtualTouchpad(joystick,0,0,false,0,0,0));
    assert(SDL_SetJoystickVirtualTouchpad(joystick,0,1,false,0,0,0));
    SDL_UpdateJoysticks();
    SDL_UpdateGamepads();
    /* A button held across overlay capture must remain hidden until released. */
    assert(pad_read_state(1,&data)==0 && data.buttons==0 && data.touch_count==0);
    assert(SDL_SetJoystickVirtualButton(joystick,SDL_GAMEPAD_BUTTON_TOUCHPAD,false));
    SDL_UpdateJoysticks(); SDL_UpdateGamepads();
    assert(pad_read_state(1,&data)==0 && data.buttons==0 && data.touch_count==0);
    /* Xbox View/Back is a left click after release unless a d-pad side was used. */
    assert(SDL_SetJoystickVirtualButton(joystick,SDL_GAMEPAD_BUTTON_BACK,true));
    SDL_UpdateJoysticks(); SDL_UpdateGamepads();
    assert(pad_read_state(1,&data)==0 && !(data.buttons & BTN_TOUCHPAD));
    assert(SDL_SetJoystickVirtualButton(joystick,SDL_GAMEPAD_BUTTON_BACK,false));
    SDL_UpdateJoysticks(); SDL_UpdateGamepads();
    assert(pad_read_state(1,&data)==0 && (data.buttons & BTN_TOUCHPAD));
    assert(data.touch_count==1 && data.touches[0].x==480 && data.touches[0].id!=0);
    usleep(200000);
    assert(pad_read_state(1,&data)==0 && !(data.buttons & BTN_TOUCHPAD));
    SDL_CloseJoystick(joystick);
    if (gamepad) SDL_CloseGamepad(gamepad);
    gamepad=NULL;
    assert(SDL_DetachVirtualJoystick(id));
    SDL_Quit();
    unlink(path);
    puts("PASS: pad ABI, touch IDs/timing, left/right clicks, Xbox Back, SDL touch coordinates, overlay capture");
}
