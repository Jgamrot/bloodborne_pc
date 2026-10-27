// SPDX-License-Identifier: GPL-2.0-or-later
#include "bbport_map.h"
#include "bbport_map_art.h"
#include "bbport_atlas_style.h"
#include "bbport_atlas_interiors.h"
#include "bbport_map_direction.h"
#include "bbport_map_controller.h"
#include "bbport_map_features.h"
#include "bbport_atlas_menu.h"
#include "bbport_atlas_paths.h"
#include "../../src/runtime_map.h"
#include "../../src/runtime_menu_sound.h"
#include "imgui.h"
#include <SDL3/SDL.h>
#include <nlohmann/json.hpp>
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <limits>
#include <mutex>
#include <sstream>
#include <string>
#include <unordered_map>
#include <vector>
#ifdef _WIN32
#include <windows.h>
#endif

namespace BbMap {
bool UsesControllerGlyphs(); // Input ownership/state is maintained by the map integration.
namespace {
using Json=nlohmann::json;
Json qa_layout;
struct Rect {float x,z,w,h;};
struct Point {float x,z;};
struct Triangle {float v[6];float y[3]{};};
struct Segment {Point a,b;};
struct Layer {float height=0,span=6,anchor=0,min_y=0,max_y=0;bool has_vertex_heights=false;std::vector<Rect> rects;std::vector<Triangle> triangles;std::vector<std::vector<Point>> outlines;std::vector<Segment> walls;};
struct Lamp {float x,y,z;std::string name;};
struct Marker {float x,y,z;std::string kind,name;int entity=0;};
struct NamedLandmark {float x,y,z,max_horizontal=60,max_vertical=6;std::string name,prefix="Near ";};
struct NamedRegion {std::string name;float min_y=-1e9f,max_y=1e9f;bool main_location=false;std::vector<Triangle> triangles;};
struct Area {std::string id,name;float bounds[4]{};std::vector<Layer> layers;std::vector<Lamp> lamps;std::vector<Marker> markers;std::vector<NamedLandmark> named_landmarks;std::vector<NamedRegion> named_regions;bool loaded=false;std::string error;BbAtlasStyle::CutCache cut_cache;BbAtlasInteriors::Cache interior_cache;};
std::recursive_mutex map_mutex;
std::vector<Area> areas;
std::filesystem::path directory,config;
std::filesystem::path name_catalog;
bool enabled=true,follow=true,preview_active=false,elevation_shading=true;
BbMapControllerChord controller_chord;
ImFont* title_font=nullptr;
std::atomic<bool> open{false};
int keyboard=0,chord=1,selected=-1,preview_area=-1;
float cx=0,cz=0,zoom=3.0f;
std::atomic<float> padx{0},pady{0};
std::atomic<float> pointer_x{0},pointer_y{0};
std::atomic<int> cycle_request{0};
std::atomic<bool> confirm_request{false},back_request{false},recenter_request{false},shading_request{false};
std::atomic<bool> pad_armed{false};
std::atomic<int> zoom_request{0},zoom_held{0};
uint64_t zoom_repeat=0;
float cursor_u=.5f,cursor_v=.5f;
int selected_destination=-1,travel_dialog=-1;
bool travel_monitor=false;
bool map_dragged=false;
std::string travel_message;
std::string atlas_error;
BbMapLocation location{};
SDL_Keycode map_keys[]={SDLK_M,SDLK_F9,SDLK_F10};
const char* key_names[] = {"M","F9","F10"};

void Save() {
    try {
        std::filesystem::create_directories(config.parent_path());
        auto temp=config;temp+=".tmp";
        {std::ofstream f(temp);if(!std::getenv("BB_ATLAS_ENABLED"))f<<"enabled="<<enabled<<"\n";f<<"keyboard="<<keyboard<<"\ncontroller="<<chord<<"\n";if(!f)throw std::runtime_error("settings write failed");}
        // Atomic replacement on Windows. Only this feature's settings are touched.
#ifdef _WIN32
        if (!MoveFileExW(temp.c_str(),config.c_str(),MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH))throw std::runtime_error("settings replacement failed");
#else
        std::filesystem::rename(temp,config);
#endif
    }catch(const std::exception& e){std::printf("Map: %s\n",e.what());}
}
bool Load(Area& a) {
    if(a.loaded)return a.error.empty();
    a.loaded=true;
    try {
        std::ifstream f(directory/(a.id+".json"));Json j;f>>j;
        const int version=j.at("version");
        if((version!=1 && version!=2) || j.at("id")!=a.id)throw std::runtime_error("Map data version mismatch");
        for(const auto& l:j.at("layers")) {
            Layer layer;
            if(version==1) {
                layer.height=l.at("height");layer.anchor=layer.height+3;
                for(const auto& r:l.at("rects")) {
                    if(r.size()!=4)throw std::runtime_error("Invalid map rectangle");
                    Rect rect{r[0],r[1],r[2],r[3]};
                    if(!std::isfinite(rect.x)||!std::isfinite(rect.z)||rect.w<=0||rect.h<=0)throw std::runtime_error("Invalid map geometry");
                    layer.rects.push_back(rect);
                }
            } else {
                layer.height=l.at("height");layer.span=l.at("span");layer.anchor=l.at("anchor");
                if(!std::isfinite(layer.height)||!std::isfinite(layer.span)||layer.span<=0||!std::isfinite(layer.anchor))throw std::runtime_error("Invalid map layer height");
                for(const auto& t:l.at("triangles")) {
                    if(t.size()!=6)throw std::runtime_error("Invalid floor triangle");
                    Triangle tri{};for(size_t k=0;k<6;++k){tri.v[k]=t[k];if(!std::isfinite(tri.v[k]))throw std::runtime_error("Invalid floor triangle");}
                    layer.triangles.push_back(tri);
                }
                if(l.contains("heights")) {
                    const auto& heights=l.at("heights");
                    if(!heights.is_array() || heights.size()!=layer.triangles.size())throw std::runtime_error("Invalid floor vertex heights");
                    layer.min_y=std::numeric_limits<float>::infinity();layer.max_y=-layer.min_y;
                    for(size_t i=0;i<heights.size();++i) {
                        if(heights[i].size()!=3)throw std::runtime_error("Invalid floor vertex heights");
                        for(size_t k=0;k<3;++k){const float y=heights[i][k];if(!std::isfinite(y))throw std::runtime_error("Invalid floor vertex heights");layer.triangles[i].y[k]=y;layer.min_y=std::min(layer.min_y,y);layer.max_y=std::max(layer.max_y,y);}
                    }
                    layer.has_vertex_heights=!layer.triangles.empty();
                }
                for(const auto& ring:l.at("outlines")) {
                    std::vector<Point> outline;outline.reserve(ring.size());
                    for(const auto& p:ring){if(p.size()!=2)throw std::runtime_error("Invalid floor outline");Point pt{p[0],p[1]};if(!std::isfinite(pt.x)||!std::isfinite(pt.z))throw std::runtime_error("Invalid floor outline");outline.push_back(pt);}
                    if(outline.size()>1)layer.outlines.push_back(std::move(outline));
                }
                for(const auto& w:l.at("walls")) {
                    if(w.size()!=4)throw std::runtime_error("Invalid wall segment");
                    Segment wall{{w[0],w[1]},{w[2],w[3]}};
                    if(!std::isfinite(wall.a.x)||!std::isfinite(wall.a.z)||!std::isfinite(wall.b.x)||!std::isfinite(wall.b.z))throw std::runtime_error("Invalid wall segment");
                    layer.walls.push_back(wall);
                }
            }
            a.layers.push_back(std::move(layer));
        }
        for(const auto& l:j.at("lamps")){const auto& p=l.at("pos");a.lamps.push_back({p[0],p[1],p[2],l.at("name")});}
        if(j.contains("markers"))for(const auto& m:j.at("markers")) {
            const auto& p=m.at("pos");const auto kind=m.at("kind").get<std::string>();
            if(p.size()==3 && (kind=="ladder" || kind=="npc" || kind=="gate") && std::isfinite(float(p[0])) && std::isfinite(float(p[1])) && std::isfinite(float(p[2])))
                a.markers.push_back({p[0],p[1],p[2],kind,m.at("name"),m.value("entity_id",0)});
        }
    }catch(const std::exception& e){a.error=e.what();}
    return a.error.empty();
}
std::string BlockId(uint32_t block) {
    char id[24];std::snprintf(id,sizeof(id),"m%02u_%02u_%02u_%02u",block>>24,(block>>16)&255,(block>>8)&255,block&255);return id;
}
int CurrentArea() {
    if(!location.valid)return -1;
    const auto id=BlockId(location.block);
    for(size_t i=0;i<areas.size();++i)if(areas[i].id==id)return int(i);
    return -1;
}
bool InTriangle(const Triangle& t,float x,float z) {
    if(x<std::min({t.v[0],t.v[2],t.v[4]})||x>std::max({t.v[0],t.v[2],t.v[4]})||z<std::min({t.v[1],t.v[3],t.v[5]})||z>std::max({t.v[1],t.v[3],t.v[5]}))return false;
    auto cross=[&](int u,int v){return (t.v[v]-t.v[u])*(z-t.v[u+1])-(t.v[v+1]-t.v[u+1])*(x-t.v[u]);};
    const float ab=cross(0,2),bc=cross(2,4),ca=cross(4,0);
    return (ab>=-.0001f&&bc>=-.0001f&&ca>=-.0001f)||(ab<=.0001f&&bc<=.0001f&&ca<=.0001f);
}
bool TriangleHeightAt(const Triangle& triangle,float x,float z,float& y) {
    const float x0=triangle.v[0],z0=triangle.v[1],x1=triangle.v[2],z1=triangle.v[3],x2=triangle.v[4],z2=triangle.v[5];
    const float denominator=(z1-z2)*(x0-x2)+(x2-x1)*(z0-z2);
    if(std::abs(denominator)<1.0e-8f)return false;
    const float a=((z1-z2)*(x-x2)+(x2-x1)*(z-z2))/denominator;
    const float b=((z2-z0)*(x-x2)+(x0-x2)*(z-z2))/denominator;
    const float c=1.0f-a-b;
    y=a*triangle.y[0]+b*triangle.y[1]+c*triangle.y[2];
    return std::isfinite(y);
}
void LoadNameCatalog() {
    try {
        name_catalog=BbAtlasPath("BB_MAP_CATALOG",directory.parent_path()/"catalog.json");
        std::ifstream f(name_catalog);if(!f)return;
        Json j;f>>j;
        for(auto& a:areas) {
            if(!j.contains(a.id))continue;
            const auto& entry=j.at(a.id);
            if(entry.contains("landmarks"))for(const auto& item:entry.at("landmarks")) {
                if(!item.contains("name")||!item.contains("pos")||item.at("pos").size()!=3)continue;
                const auto& p=item.at("pos");NamedLandmark m;
                m.name=item.at("name");m.x=p[0];m.y=p[1];m.z=p[2];
                if(item.contains("max_horizontal_distance"))m.max_horizontal=item.at("max_horizontal_distance");
                if(item.contains("max_vertical_distance"))m.max_vertical=item.at("max_vertical_distance");
                if(item.contains("subtitle_prefix"))m.prefix=item.at("subtitle_prefix");
                if(std::isfinite(m.x)&&std::isfinite(m.y)&&std::isfinite(m.z)&&m.max_horizontal>0&&m.max_vertical>=0)a.named_landmarks.push_back(std::move(m));
            }
            if(entry.contains("regions"))for(const auto& item:entry.at("regions")) {
                if(!item.contains("name"))continue;
                NamedRegion region;region.name=item.at("name");
                if(item.contains("shape")&&item.at("shape")!="footprint")continue;
                if(item.contains("min_y"))region.min_y=item.at("min_y");
                if(item.contains("max_y"))region.max_y=item.at("max_y");
                if(!std::isfinite(region.min_y)||!std::isfinite(region.max_y)||region.min_y>region.max_y)continue;
                if(item.contains("main_location"))region.main_location=item.at("main_location");
                if(item.contains("triangles"))for(const auto& t:item.at("triangles")) {
                    if(!t.is_array()||t.size()!=6)continue;
                    Triangle tri{};bool valid=true;
                    for(size_t k=0;k<6;++k){tri.v[k]=t[k];if(!std::isfinite(tri.v[k]))valid=false;}
                    if(valid)region.triangles.push_back(tri);
                }
                if(!region.triangles.empty())a.named_regions.push_back(std::move(region));
            }
        }
    }catch(const std::exception& e){std::printf("Map names: %s\n",e.what());}
}
std::string LocationTitle(const Area& a) {
    for(const auto& region:a.named_regions)if(region.main_location&&location.y>=region.min_y-1&&location.y<=region.max_y+2)
        for(const auto& t:region.triangles)if(InTriangle(t,location.x,location.z))return region.name;
    return a.name;
}
std::string LocationSubtitle(const Area& a) {
    const auto title=LocationTitle(a);
    for(const auto& region:a.named_regions)if(region.name!=title&&location.y>=region.min_y-1&&location.y<=region.max_y+2)
        for(const auto& t:region.triangles)if(InTriangle(t,location.x,location.z))return region.name;
    const NamedLandmark* nearest=nullptr;float best=std::numeric_limits<float>::infinity();
    for(const auto& landmark:a.named_landmarks) {
        const float dx=landmark.x-location.x,dz=landmark.z-location.z,dy=std::abs(landmark.y-location.y);
        const float horizontal=std::hypot(dx,dz);
        if(horizontal>landmark.max_horizontal||dy>landmark.max_vertical)continue;
        const float distance=std::hypot(horizontal,dy);if(distance<best){best=distance;nearest=&landmark;}
    }
    return nearest?nearest->prefix+nearest->name:std::string{};
}
float MapUiScale() {
    const auto size=ImGui::GetIO().DisplaySize;
    return BbAtlasStyle::Layout(size.x,size.y).scale;
}
void Fit() {
    if(selected<0)return;
    const auto& a=areas[selected];cx=(a.bounds[0]+a.bounds[2])*0.5f;cz=(a.bounds[1]+a.bounds[3])*0.5f;
    const auto size=ImGui::GetIO().DisplaySize;
    const auto canvas=BbAtlasStyle::Layout(size.x,size.y).Canvas();
    zoom=std::clamp(std::min(canvas.w/(a.bounds[2]-a.bounds[0]),canvas.h/(a.bounds[3]-a.bounds[1])),0.15f,25.0f);
    follow=false;
}
void Recenter() {
    preview_active=false;preview_area=-1;selected_destination=-1;cursor_u=cursor_v=.5f;
    const int current=CurrentArea();
    selected=current;follow=true;zoom=9.0f*MapUiScale();
    // Draw loads the area. Opening from the quick menu runs this on the game's pad thread,
    // where reading and parsing the area's file held the game up.
    if(selected>=0){cx=location.x;cz=location.z;}
}
void SetOpen(bool value) {
    std::lock_guard<std::recursive_mutex> map_guard(map_mutex);
    open=enabled && value;padx=pady=0;
    pointer_x=pointer_y=0;cycle_request=0;confirm_request=false;back_request=false;
    pad_armed=false;zoom_request=zoom_held=0;recenter_request=shading_request=false;
    cursor_u=cursor_v=.5f;selected_destination=-1;travel_dialog=-1;
    if(open){runtime_map_location(&location);Recenter();preview_active=false;preview_area=-1;}
}
int AutoLayer(const Area& a) {
    int nearest=-1,local=-1;float distance=std::numeric_limits<float>::infinity(),local_distance=std::numeric_limits<float>::infinity();
    for(size_t i=0;i<a.layers.size();++i){
        const auto& layer=a.layers[i];float d=std::abs(location.y-layer.anchor);
        if(d<distance){distance=d;nearest=int(i);}
        for(const auto& t:layer.triangles)if(InTriangle(t,location.x,location.z)){
            float surface_y=layer.anchor;
            if(layer.has_vertex_heights&&!TriangleHeightAt(t,location.x,location.z,surface_y))continue;
            const float surface_distance=std::abs(location.y-surface_y);
            if(surface_distance<local_distance){local_distance=surface_distance;local=int(i);}
        }
        if(layer.triangles.empty())for(const auto& r:layer.rects)if(location.x>=r.x && location.x<=r.x+r.w && location.z>=r.z && location.z<=r.z+r.h){
            if(d<local_distance){local_distance=d;local=int(i);}break;
        }
    }
    return local>=0?local:nearest;
}
// A finished hatch list never changes, so it gets a uniform grid once: a frame then visits the
// lines under the canvas, not every line of the area (hundreds of thousands at close zoom).
struct LineGrid {
    const BbAtlasStyle::Line* source=nullptr;size_t count=0;
    float x0=0,z0=0,cell=1;int nx=0,nz=0;
    std::vector<uint32_t> offsets,items,broad,marks;uint32_t serial=0;
    void Cells(const BbAtlasStyle::Line& l,int& a0,int& b0,int& a1,int& b1)const{
        a0=std::clamp(int((std::min(l.a.x,l.b.x)-x0)/cell),0,nx-1);a1=std::clamp(int((std::max(l.a.x,l.b.x)-x0)/cell),0,nx-1);
        b0=std::clamp(int((std::min(l.a.z,l.b.z)-z0)/cell),0,nz-1);b1=std::clamp(int((std::max(l.a.z,l.b.z)-z0)/cell),0,nz-1);
    }
    void Build(const std::vector<BbAtlasStyle::Line>& lines){
        source=lines.data();count=lines.size();offsets.clear();items.clear();broad.clear();marks.assign(count,0);serial=0;nx=nz=0;
        if(lines.empty())return;
        float x1=-std::numeric_limits<float>::infinity(),z1=x1;x0=z0=std::numeric_limits<float>::infinity();
        for(const auto& l:lines){x0=std::min({x0,l.a.x,l.b.x});z0=std::min({z0,l.a.z,l.b.z});x1=std::max({x1,l.a.x,l.b.x});z1=std::max({z1,l.a.z,l.b.z});}
        cell=std::max(4.f,std::max(x1-x0,z1-z0)/128.f);
        nx=std::min(256,int((x1-x0)/cell)+1);nz=std::min(256,int((z1-z0)/cell)+1);
        offsets.assign(size_t(nx)*nz+1,0);
        auto each=[&](auto&& fn){for(uint32_t i=0;i<count;++i){int a0,b0,a1,b1;Cells(lines[i],a0,b0,a1,b1);
            // A long diagonal would fill a square of cells; such lines are always visited.
            if((a1-a0+1)*(b1-b0+1)>64){fn(i,-1);continue;}
            for(int z=b0;z<=b1;++z)for(int x=a0;x<=a1;++x)fn(i,z*nx+x);}};
        each([&](uint32_t i,int c){if(c<0)broad.push_back(i);else ++offsets[c+1];});
        for(size_t c=1;c<offsets.size();++c)offsets[c]+=offsets[c-1];
        items.resize(offsets.back());auto fill=offsets;
        each([&](uint32_t i,int c){if(c>=0)items[fill[c]++]=i;});
    }
    template<class F> void Visit(const std::vector<BbAtlasStyle::Line>& lines,float qx0,float qz0,float qx1,float qz1,F&& fn){
        if(!count)return;
        if(++serial==0){std::fill(marks.begin(),marks.end(),0);serial=1;}
        for(auto i:broad)fn(lines[i]);
        if(qx1<x0||qz1<z0||qx0>x0+nx*cell||qz0>z0+nz*cell)return;
        const int a0=std::clamp(int((qx0-x0)/cell),0,nx-1),a1=std::clamp(int((qx1-x0)/cell),0,nx-1);
        const int b0=std::clamp(int((qz0-z0)/cell),0,nz-1),b1=std::clamp(int((qz1-z0)/cell),0,nz-1);
        for(int z=b0;z<=b1;++z)for(int x=a0;x<=a1;++x){const int c=z*nx+x;
            for(uint32_t k=offsets[c];k<offsets[c+1];++k){const auto i=items[k];if(marks[i]!=serial){marks[i]=serial;fn(lines[i]);}}}
    }
};
std::unordered_map<const std::vector<BbAtlasStyle::Line>*,LineGrid> line_grids;
template<class F> void LinesInView(const std::vector<BbAtlasStyle::Line>& lines,float x0,float z0,float x1,float z1,F&& fn){
    auto& grid=line_grids[&lines];
    if(grid.source!=lines.data()||grid.count!=lines.size())grid.Build(lines);
    grid.Visit(lines,x0,z0,x1,z1,fn);
}
int PrimaryLayer(const Area& a) {
    if(a.layers.empty())return -1;
    size_t best=0;float footprint=0;
    for(size_t i=0;i<a.layers.size();++i){
        float area=0;
        for(const auto& t:a.layers[i].triangles)area+=std::abs((t.v[2]-t.v[0])*(t.v[5]-t.v[1])-(t.v[4]-t.v[0])*(t.v[3]-t.v[1]))*.5f;
        for(const auto& r:a.layers[i].rects)area+=r.w*r.h;
        if(area>footprint){best=i;footprint=area;}
    }
    return int(best);
}
}

bool Testing::AutoLayerSelectsClosestSurface() {
    Area synthetic;
    Layer stair;stair.anchor=1.0f;stair.span=3.0f;stair.has_vertex_heights=true;stair.min_y=4.0f;stair.max_y=4.0f;
    Triangle stair_surface{};stair_surface.v[0]=0;stair_surface.v[1]=0;stair_surface.v[2]=2;stair_surface.v[3]=0;stair_surface.v[4]=0;stair_surface.v[5]=2;stair_surface.y[0]=stair_surface.y[1]=stair_surface.y[2]=4.0f;stair.triangles.push_back(stair_surface);
    Layer balcony;balcony.anchor=5.0f;balcony.span=3.0f;balcony.has_vertex_heights=true;balcony.min_y=2.5f;balcony.max_y=2.5f;
    Triangle balcony_surface=stair_surface;balcony_surface.y[0]=balcony_surface.y[1]=balcony_surface.y[2]=2.5f;balcony.triangles.push_back(balcony_surface);
    synthetic.layers.push_back(std::move(stair));synthetic.layers.push_back(std::move(balcony));
    const BbMapLocation previous=location;location={.5f,3.8f,.5f,0.0f,0,1};
    const bool passed=AutoLayer(synthetic)==0;location=previous;return passed;
}
void Init() {
    std::lock_guard<std::recursive_mutex> map_guard(map_mutex);
    directory=BbAtlasPath("BB_MAP_DIR","navigation-map/maps");
    config=BbAtlasPath("BB_MAP_CONFIG",directory.parent_path()/"settings.ini");
    std::ifstream settings(config);std::string line;
    while(std::getline(settings,line)) {
        auto eq=line.find('=');if(eq==std::string::npos)continue;
        const auto key=line.substr(0,eq);int value=std::atoi(line.c_str()+eq+1);
        if(key=="enabled")enabled=value!=0;
        if(key=="keyboard")keyboard=std::clamp(value,0,2);
        if(key=="controller")chord=std::clamp(value,0,2);
    }
    if(const char* forced=std::getenv("BB_ATLAS_ENABLED"))enabled=std::atoi(forced)!=0;
    try {
        std::ifstream f(directory/"atlas.json");Json atlas;f>>atlas;
        if(atlas.at("version")!=1)throw std::runtime_error("Map atlas version mismatch");
        for(const auto& j:atlas.at("maps")) {
            if(!j.contains("id"))continue;
            Area a;a.id=j.at("id");a.name=j.at("name");
            if(a.id.size()!=12 || a.id.find_first_not_of("m0123456789_")!=std::string::npos)continue;
            const auto& b=j.at("bounds");for(int k=0;k<4;++k)a.bounds[k]=b[k];
            if(a.bounds[2]>a.bounds[0] && a.bounds[3]>a.bounds[1])areas.push_back(std::move(a));
        }
    }catch(const std::exception& e){atlas_error=e.what();}
    LoadNameCatalog();
    BbMapFeatures::Init(directory);
    std::printf("Map: %zu areas, %s toggles, enabled=%d\n",areas.size(),key_names[keyboard],enabled);
    controller_chord.SetEnabled(enabled && chord==2);
}
bool IsOpen(){return open;}
bool Enabled(){return enabled;}
int ShortcutMode(){return chord;}
bool UsesControllerGlyphs(){return BbAtlasMenu::UsesControllerGlyphs();}
void OpenFromMenu(){SetOpen(true);}
// The game's pad thread. Requests only, no map_mutex: Draw holds it for a whole frame of
// drawing, and waiting for it here held up the game.
void MappedPad(unsigned rising,unsigned char lx,unsigned char ly,unsigned char rx,unsigned char ry,unsigned held) {
    if(!open)return;
    if(!pad_armed){if(!held&&std::abs(int(lx)-128)<24&&std::abs(int(ly)-128)<24&&std::abs(int(rx)-128)<24&&std::abs(int(ry)-128)<24)pad_armed=true;else return;}
    if(rising&0x1000u)recenter_request=true;
    if(rising&0x8000u)shading_request=true;
    if((held&0xc00u)!=0xc00u && (rising&0xc00u)==0x400u)cycle_request=-1;
    if((held&0xc00u)!=0xc00u && (rising&0xc00u)==0x800u)cycle_request=1;
    if((rising&0x300u)==0x100u)zoom_request=-1;
    if((rising&0x300u)==0x200u)zoom_request=1;
    zoom_held=(held&0x300u)==0x100u?-1:(held&0x300u)==0x200u?1:0;
    if(rising&runtime_map_confirm_button())confirm_request=true;
    auto axis=[](unsigned char value){const float v=(int(value)-128)/127.f;return std::abs(v)>.18f?v:0.f;};
    pointer_x=axis(lx);pointer_y=axis(ly);padx=axis(rx);pady=axis(ry);
}
bool CapturesInput(){return open || controller_chord.WantsCapture();}
void Tick(){std::lock_guard<std::recursive_mutex> map_guard(map_mutex);if(controller_chord.Tick(SDL_GetTicks()))SetOpen(!open);if(travel_monitor&&runtime_atlas_travel_status()<0){travel_monitor=false;travel_message="Travel was rejected or did not complete. No second request was sent.";SetOpen(true);}}
void Close(){std::lock_guard<std::recursive_mutex> map_guard(map_mutex);open=false;padx=pady=0;pointer_x=pointer_y=0;zoom_held=0;travel_dialog=-1;}
void Back(){back_request=true;}
namespace {
struct QaMouse {std::string action;float x=0,y=0,wheel=0;};
std::atomic<unsigned> qa_mouse_events{0};
void PushQaMouse(void* opaque) {
    auto* job=static_cast<QaMouse*>(opaque);
    // Run on SDL's window thread. Never send OS input or select another app's window.
    int count=0;SDL_Window** windows=SDL_GetWindows(&count);
    SDL_Window* window=windows&&count==1?windows[0]:nullptr;
    int width=0,height=0;
    const float density=window?SDL_GetWindowPixelDensity(window):0;
    if(window&&density>0&&job->action=="qa-resize"){
        if(job->x>=640&&job->x<=7680&&job->y>=360&&job->y<=4320){SDL_SetWindowSize(window,int(job->x/density),int(job->y/density));qa_mouse_events.fetch_add(1);}
        SDL_free(windows);delete job;return;
    }
    if(window && density>0 && SDL_GetWindowSizeInPixels(window,&width,&height) &&
       job->x>=0 && job->y>=0 && job->x<width && job->y<height) {
        const auto id=SDL_GetWindowID(window);SDL_Event event{};
        const float x=job->x/density,y=job->y/density;
        static bool held=false;
        if(job->action=="qa-key-insert") {
            event.type=SDL_EVENT_KEY_DOWN;event.key.windowID=id;
            event.key.key=SDLK_INSERT;event.key.scancode=SDL_SCANCODE_INSERT;event.key.down=true;
            if(SDL_PushEvent(&event))qa_mouse_events.fetch_add(1);
            event.type=SDL_EVENT_KEY_UP;event.key.down=false;
        } else if(job->action=="qa-mouse-move") {
            event.type=SDL_EVENT_MOUSE_MOTION;event.motion.windowID=id;
            event.motion.x=x;event.motion.y=y;event.motion.state=held?SDL_BUTTON_LMASK:0;
        } else if(job->action=="qa-mouse-down" || job->action=="qa-mouse-up") {
            held=job->action=="qa-mouse-down";
            event.type=held?SDL_EVENT_MOUSE_BUTTON_DOWN:SDL_EVENT_MOUSE_BUTTON_UP;
            event.button.windowID=id;event.button.x=x;event.button.y=y;
            event.button.button=SDL_BUTTON_LEFT;event.button.down=held;event.button.clicks=1;
        } else if(job->action=="qa-mouse-wheel") {
            event.type=SDL_EVENT_MOUSE_WHEEL;event.wheel.windowID=id;
            event.wheel.mouse_x=x;event.wheel.mouse_y=y;event.wheel.y=job->wheel;
        }
        if(event.type && SDL_PushEvent(&event))qa_mouse_events.fetch_add(1);
    }
    SDL_free(windows);delete job;
}
void QueueQaMouse(const std::string& command) {
    const char* qa=std::getenv("BB_ATLAS_QA");
    if(!qa || std::strcmp(qa,"1"))return;
    std::istringstream input(command);QaMouse job;std::string extra;
    if(!(input>>job.action>>job.x>>job.y) || !std::isfinite(job.x) || !std::isfinite(job.y))return;
    if(job.action=="qa-mouse-wheel") {
        if(!(input>>job.wheel) || !std::isfinite(job.wheel) || std::abs(job.wheel)>20)return;
    } else if(job.action!="qa-mouse-move" && job.action!="qa-mouse-down" && job.action!="qa-mouse-up" && job.action!="qa-resize")return;
    if(input>>extra)return;
    auto* copy=new QaMouse(job);
    if(!SDL_RunOnMainThread(PushQaMouse,copy,false))delete copy;
}
}
void PollTestCommands() {
    std::lock_guard<std::recursive_mutex> map_guard(map_mutex);
    static const char* control=std::getenv("BB_MAP_TEST_CONTROL");
    if(!control || !*control)return;
    static auto last=std::chrono::steady_clock::time_point{};
    const auto now=std::chrono::steady_clock::now();
    if(now-last<std::chrono::milliseconds(100))return;last=now;
    std::ifstream input(control);std::string command;
    if(input && std::getline(input,command)) {
        input.close();std::error_code ec;std::filesystem::remove(control,ec);
        if(command.rfind("qa-mouse-",0)==0 || command.rfind("qa-resize ",0)==0)QueueQaMouse(command);
        if(command=="qa-key-insert") {
            const char* qa=std::getenv("BB_ATLAS_QA");
            if(qa && !std::strcmp(qa,"1")) {
                auto* job=new QaMouse{"qa-key-insert"};
                if(!SDL_RunOnMainThread(PushQaMouse,job,false))delete job;
            }
        }
        if(command=="open" || command=="close") {SDL_Event e{};e.type=SDL_EVENT_KEY_DOWN;e.key.key=map_keys[keyboard];if((command=="open")!=bool(open))HandleEvent(e);}
        if(command=="fit")Fit();
        if(command=="recenter")Recenter();
        if(command=="zoom-in"||command=="zoom-out")MappedPad(command=="zoom-in"?0x200:0x100,128,128);
        if(command=="pan-right"||command=="pan-stop")MappedPad(0,128,128,command=="pan-right"?205:128,128);
        if(command=="lamp-next"||command=="lamp-previous")cycle_request=command=="lamp-next"?1:-1;
        if(command=="map-confirm")confirm_request=true;
        if(command=="map-back")back_request=true;
        if(command=="controller-back")Close();
        if(command=="live"){preview_active=false;preview_area=-1;Recenter();}
        if(command=="shading")elevation_shading=!elevation_shading;
        if(command=="controller-elevation")MappedPad(0x8000,128,128);
        if(command.rfind("area ",0)==0) {
            const auto id=command.substr(5);
            for(size_t i=0;i<areas.size();++i)if(areas[i].id==id){if(!open)SetOpen(true);preview_active=true;preview_area=selected=int(i);Load(areas[i]);Fit();break;}
        }
        if(command=="disable"){enabled=false;Close();controller_chord.SetEnabled(false);}
        if(command=="enable"){enabled=true;controller_chord.SetEnabled(chord==2);}
        if(command=="controller-map"){SDL_Event e{};e.type=SDL_EVENT_GAMEPAD_BUTTON_DOWN;e.gbutton.button=SDL_GAMEPAD_BUTTON_RIGHT_STICK;HandleEvent(e);}
    }
    BbMapLocation sample{};runtime_map_location(&sample);location=sample;
    if(const char* trace=std::getenv("BB_MAP_TEST_TRACE")) {
        const auto temp=std::string(trace)+".tmp";
        BbMenuSoundStats audio_stats{};runtime_audio_menu_stats(&audio_stats);
        {BbMapMenu menu_state{};runtime_map_menu_state(&menu_state);std::ofstream f(temp);const int live=CurrentArea();int live_layer=-1;if(live>=0&&Load(areas[live]))live_layer=AutoLayer(areas[live]);f<<Json{{"ui",qa_layout},{"audio_decoded_move",audio_stats.decoded_move},{"audio_decoded_select",audio_stats.decoded_select},{"audio_queued_move",audio_stats.queued_move},{"audio_queued_select",audio_stats.queued_select},{"audio_mixed_move",audio_stats.mixed_move},{"audio_mixed_select",audio_stats.mixed_select},{"audio_muted",audio_stats.muted},{"valid",sample.valid!=0},{"block",sample.block},{"x",sample.x},{"y",sample.y},{"z",sample.z},{"yaw",sample.yaw},{"menu",runtime_map_menu_open()!=0},{"menu_supported",menu_state.supported!=0},{"menu_top",menu_state.top_level!=0},{"native_focus",menu_state.selected},{"atlas_focus",BbAtlasMenu::Focused()},{"tile",BbAtlasMenu::Visible()},{"confirm",runtime_map_confirm_button()},{"open",bool(open)},{"capture",CapturesInput()},{"qa_mouse_events",qa_mouse_events.load()},{"enabled",enabled},{"shading",elevation_shading},{"travel_supported",runtime_atlas_travel_supported()!=0},{"travel_status",runtime_atlas_travel_status()},{"available_lamps",BbMapFeatures::Available().size()},{"selected_destination",selected_destination},{"travel_dialog",travel_dialog},{"items_enabled",BbMapFeatures::ItemsEnabled()},{"fog_enabled",BbMapFeatures::FogEnabled()},{"feature_error",BbMapFeatures::Error()},{"lamp_central",runtime_atlas_flag(12417830)},{"lamp_cathedral",runtime_atlas_flag(12407810)},{"boss_gascoigne",runtime_atlas_flag(12411800)},{"boss_amelia",runtime_atlas_flag(12401800)},{"selected",selected},{"current_layer",live_layer},{"zoom",zoom},{"cx",cx},{"cz",cz},{"follow",follow},{"title",live>=0?LocationTitle(areas[live]):std::string{}},{"subtitle",live>=0?LocationSubtitle(areas[live]):std::string{}}}.dump();}
#ifdef _WIN32
        MoveFileExA(temp.c_str(),trace,MOVEFILE_REPLACE_EXISTING);
#else
        std::error_code ec;std::filesystem::rename(temp,trace,ec);
#endif
    }
}
bool HandleEvent(const SDL_Event& e) {
    std::lock_guard<std::recursive_mutex> map_guard(map_mutex);
    if(controller_chord.HandleEvent(e))return true;
    if(!enabled)return false;
    if(e.type==SDL_EVENT_KEY_DOWN && !e.key.repeat) {
        if(e.key.key==map_keys[keyboard]){SetOpen(!open);return true;}
        if(open && e.key.key==SDLK_ESCAPE){Back();return true;}
        if(open && e.key.key==SDLK_Q){cycle_request=-1;return true;}
        if(open && e.key.key==SDLK_E){cycle_request=1;return true;}
        if(open && (e.key.key==SDLK_RETURN || e.key.key==SDLK_KP_ENTER)){confirm_request=true;return true;}
        if(open && (e.key.key==SDLK_MINUS || e.key.key==SDLK_KP_MINUS)){zoom=std::max(.15f*MapUiScale(),zoom/1.25f);return true;}
        if(open && (e.key.key==SDLK_EQUALS || e.key.key==SDLK_KP_PLUS)){zoom=std::min(25.f*MapUiScale(),zoom*1.25f);return true;}
        if(open && e.key.key==SDLK_HOME){Recenter();return true;}
        if(open && e.key.key==SDLK_H){elevation_shading=!elevation_shading;return true;}
    }
    // Actual mapped controller input is routed once at runtime_pad's logical
    // sample boundary. SDL physical events cannot bypass remapped bindings.
    if(e.type==SDL_EVENT_WINDOW_FOCUS_LOST)Close();
    return false;
}
void Settings() {
    std::lock_guard<std::recursive_mutex> map_guard(map_mutex);
    ImGui::SeparatorText("Navigation map");
    ImGui::BeginDisabled(std::getenv("BB_ATLAS_ENABLED")!=nullptr);
    if(ImGui::Checkbox("Enable full-screen map",&enabled)){if(!enabled)Close();controller_chord.SetEnabled(enabled && chord==2);Save();}
    ImGui::EndDisabled();
    if(std::getenv("BB_ATLAS_ENABLED"))ImGui::TextDisabled("Enable or disable Hunter's Atlas in the launcher.");
    if(ImGui::Combo("Map key",&keyboard,key_names,3))Save();
    const char* chords[]={"Disabled","Open game menu, then click right stick (R3)","Hold LB / L1 + RB / R1 + Menu / Options for about 650 ms"};
    if(ImGui::Combo("Map controller shortcut",&chord,chords,3)){controller_chord.SetEnabled(enabled && chord==2);Save();}
    if(enabled && ImGui::Button("Open map"))SetOpen(true);
    ImGui::TextWrapped("Select Map in the game's quick menu, or click its fourth tile. Back returns to the same menu. Keyboard and controller shortcuts are optional.");
    if(!atlas_error.empty())ImGui::TextWrapped("Map data unavailable: %s",atlas_error.c_str());
}
void SetTitleFont(ImFont* font){title_font=font;}
ImFont* TitleFont(){return title_font?title_font:ImGui::GetFont();}
void Draw() {
    std::lock_guard<std::recursive_mutex> map_guard(map_mutex);
    if(!open)return;
    runtime_map_location(&location);
    BbMapFeatures::Refresh(location.valid!=0);
    const bool cancel_dialog=back_request.exchange(false);
    if(cancel_dialog && travel_dialog<0){Close();return;}
    const bool confirm=confirm_request.exchange(false),dialog_was_open=travel_dialog>=0;
    if(recenter_request.exchange(false)&&!dialog_was_open)Recenter();
    if(shading_request.exchange(false)&&!dialog_was_open)elevation_shading=!elevation_shading;
    int zoom_step=zoom_request.exchange(0);
    if(!dialog_was_open){if(zoom_step)zoom_repeat=SDL_GetTicks();else if(zoom_held&&SDL_GetTicks()-zoom_repeat>=180){zoom_step=zoom_held;zoom_repeat=SDL_GetTicks();}if(zoom_step)zoom=std::clamp(zoom*(zoom_step>0?1.25f:.8f),.15f*MapUiScale(),25.f*MapUiScale());}
    const int direction=cycle_request.exchange(0);
    const auto& destinations=BbMapFeatures::Destinations();
    Json drawn_lamps=Json::array();
    if(direction && !dialog_was_open && BbMapFeatures::TravelEnabled()) {
        const auto available_destinations=BbMapFeatures::Available();
        if(!available_destinations.empty()) {
            auto found=std::find(available_destinations.begin(),available_destinations.end(),selected_destination);
            int next=found==available_destinations.end()?(direction>0?0:int(available_destinations.size())-1):
                (int(found-available_destinations.begin())+direction+int(available_destinations.size()))%int(available_destinations.size());
            selected_destination=available_destinations[next];const auto& d=destinations[selected_destination];
            for(size_t i=0;i<areas.size();++i)if(areas[i].id==d.area){selected=int(i);preview_active=true;preview_area=selected;follow=false;Load(areas[i]);cx=d.x;cz=d.z;cursor_u=cursor_v=.5f;break;}
        }else travel_message="No available lamps for this character.";
    }
    const int current=CurrentArea();
    if(!preview_active) {
        if(current!=selected){selected=current;follow=true;if(current>=0)zoom=9.0f*MapUiScale();}
        if(current>=0 && follow){cx=location.x;cz=location.z;Load(areas[current]);}
    }
    auto* vp=ImGui::GetMainViewport();const float scale=MapUiScale();
    ImGui::SetNextWindowPos(vp->Pos);ImGui::SetNextWindowSize(vp->Size);
    ImGui::SetNextWindowBgAlpha(1.0f);
    ImGui::Begin("Hunter's Atlas##map",nullptr,ImGuiWindowFlags_NoDecoration|ImGuiWindowFlags_NoMove|ImGuiWindowFlags_NoSavedSettings|ImGuiWindowFlags_NoBringToFrontOnFocus);
    const ImVec2 screen=ImGui::GetWindowPos(),full=ImGui::GetWindowSize();auto* draw=ImGui::GetWindowDrawList();
    const ImU32 paper=IM_COL32(223,214,187,255),muted=IM_COL32(185,180,161,255);
    BbMapArt::DrawBackground(draw,screen,ImVec2(screen.x+full.x,screen.y+full.y));
    const BbAtlasStyle::Layout layout(full.x,full.y,screen.x,screen.y);
    auto at=[&](float x,float y){const auto p=layout.At(x,y);return ImVec2(p.x,p.z);};
    auto ornament=[&](float x,float y,float r,ImU32 color){const auto p=at(x,y);const float d=r*scale;draw->AddQuad(ImVec2(p.x-d,p.y),ImVec2(p.x,p.y-d*.55f),ImVec2(p.x+d,p.y),ImVec2(p.x,p.y+d*.55f),color,.7f*scale);};
    const ImU32 rule=IM_COL32(152,146,128,125);
    draw->AddRect(at(10,8),at(1270,710),IM_COL32(156,148,126,95),0,0,.8f*scale);
    // Frame details remain decoration; no semantic map geometry is created.
    for(float x:{10.f,1270.f})for(float y:{8.f,710.f}){const float sx=x<640?1.f:-1.f,sy=y<360?1.f:-1.f;draw->AddBezierCubic(at(x,y+sy*42),at(x+sx*3,y+sy*4),at(x+sx*24,y+sy*26),at(x+sx*42,y),rule,.7f*scale);ornament(x+sx*16,y+sy*15,4,rule);}
    const bool available=selected>=0&&Load(areas[selected])&&(!preview_active?location.valid&&current==selected:true);
    const std::string title=available?(preview_active?areas[selected].name:LocationTitle(areas[selected])):(location.valid?"Location unavailable":"Awaiting your location");
    const std::string subtitle=available?(preview_active&&selected_destination>=0?destinations[selected_destination].name:LocationSubtitle(areas[selected])):std::string{};
    ImFont* font=title_font?title_font:ImGui::GetFont();
    // Fit the actual UTF-8 string, then align visible glyph bounds rather than
    // assuming a font's nominal point size equals its cap height.
    auto centered=[&](const std::string& text,float visible_top,float preferred,float minimum,float max_width,float region_height,ImU32 color){
        float size=preferred*scale;const float limit=max_width*scale;
        auto extent=font->CalcTextSizeA(size,FLT_MAX,0,text.c_str());
        if(extent.x>limit)size=std::max(minimum*scale,size*limit/extent.x);
        extent=font->CalcTextSizeA(size,FLT_MAX,0,text.c_str());
        auto glyphBounds=[&](float at_size){
            float top=at_size,bottom=0;auto* baked=font->GetFontBaked(at_size);
            for(size_t i=0;i<text.size();){uint32_t ch=static_cast<unsigned char>(text[i++]);int extra=0;if(ch>=0xc0&&ch<0xe0){ch&=31;extra=1;}else if(ch>=0xe0&&ch<0xf0){ch&=15;extra=2;}else if(ch>=0xf0){ch&=7;extra=3;}for(int j=0;j<extra&&i<text.size();++j)ch=(ch<<6)|(static_cast<unsigned char>(text[i++])&63);if(auto* g=baked->FindGlyph(ImWchar(ch));g&&g->Visible){top=std::min(top,g->Y0);bottom=std::max(bottom,g->Y1);}}
            return std::pair{top,bottom};
        };
        auto bounds=glyphBounds(size);
        if(bounds.second-bounds.first>region_height*scale){size*=region_height*scale/(bounds.second-bounds.first);bounds=glyphBounds(size);extent=font->CalcTextSizeA(size,FLT_MAX,0,text.c_str());}
        const float glyph_top=bounds.first;
        const float top=layout.y+visible_top*scale;
        if(extent.x>limit){size=std::min(minimum*.8f,region_height*.5f)*scale;draw->PushClipRect(at((1280-max_width)*.5f,visible_top-2),at((1280+max_width)*.5f,visible_top+region_height),true);draw->AddText(font,size,ImVec2(layout.x+(1280*scale-limit)*.5f,top),color,text.c_str(),nullptr,limit);draw->PopClipRect();}
        else draw->AddText(font,size,ImVec2(layout.x+(1280*scale-extent.x)*.5f,top-glyph_top),color,text.c_str());
    };
    centered(title,BbAtlasStyle::Layout::title_top,BbAtlasStyle::Layout::title_size,BbAtlasStyle::Layout::title_min,BbAtlasStyle::Layout::title_width,BbAtlasStyle::Layout::title_region_h,paper);
    draw->AddLine(at(320,BbAtlasStyle::Layout::header_rule),at(960,BbAtlasStyle::Layout::header_rule),rule,.8f*scale);
    for(float x:{336.f,640.f,944.f})ornament(x,BbAtlasStyle::Layout::header_rule,x==640?5.f:3.f,rule);
    if(!subtitle.empty())centered(subtitle,BbAtlasStyle::Layout::subtitle_top,BbAtlasStyle::Layout::subtitle_size,BbAtlasStyle::Layout::subtitle_min,BbAtlasStyle::Layout::subtitle_width,BbAtlasStyle::Layout::subtitle_region_h,muted);
    const auto canvas=layout.Canvas();
    const ImVec2 origin(canvas.x,canvas.y),canvas_size(canvas.w,canvas.h);
    draw->PushClipRect(origin,ImVec2(origin.x+canvas_size.x,origin.y+canvas_size.y),true);
    ImGui::SetCursorScreenPos(origin);ImGui::InvisibleButton("atlas-canvas",canvas_size,ImGuiButtonFlags_MouseButtonLeft);
    const bool hovered=ImGui::IsItemHovered();const ImVec2 canvas_center(origin.x+canvas_size.x*.5f,origin.y+canvas_size.y*.5f);
    if(ImGui::IsMouseClicked(ImGuiMouseButton_Left))map_dragged=false;
    if(hovered&&ImGui::IsMouseDragging(ImGuiMouseButton_Left))map_dragged=true;
    if(!dialog_was_open&&hovered&&ImGui::IsMouseDragging(ImGuiMouseButton_Left)){follow=false;cx-=ImGui::GetIO().MouseDelta.x/zoom;cz+=ImGui::GetIO().MouseDelta.y/zoom;}
    if(!dialog_was_open&&hovered&&ImGui::GetIO().MouseWheel)zoom=std::clamp(zoom*std::pow(1.2f,ImGui::GetIO().MouseWheel),.15f,25.0f);
    if(!dialog_was_open){cursor_u=std::clamp(cursor_u+pointer_x.load()*500*ImGui::GetIO().DeltaTime/std::max(1.f,canvas_size.x),0.f,1.f);cursor_v=std::clamp(cursor_v+pointer_y.load()*500*ImGui::GetIO().DeltaTime/std::max(1.f,canvas_size.y),0.f,1.f);}
    const ImVec2 pointer=UsesControllerGlyphs()?ImVec2(origin.x+canvas_size.x*cursor_u,origin.y+canvas_size.y*cursor_v):ImGui::GetIO().MousePos;
    if(!dialog_was_open&&(padx||pady)){follow=false;cx+=padx*350*ImGui::GetIO().DeltaTime/zoom;cz-=pady*350*ImGui::GetIO().DeltaTime/zoom;}
    auto project=[&](float x,float z){return ImVec2(canvas_center.x+(x-cx)*zoom,canvas_center.y-(z-cz)*zoom);};
    float render_y=location.y;
    // On screen first: a projection is far cheaper than the fog's region tests.
    auto on_screen=[&](float minx,float minz,float maxx,float maxz){const auto p=project(minx,maxz),q=project(maxx,minz);return !(q.x<origin.x||p.x>origin.x+canvas_size.x||q.y<origin.y||p.y>origin.y+canvas_size.y);};
    auto revealed_box=[&](float minx,float minz,float maxx,float maxz){return selected<0||(BbMapFeatures::Revealed(areas[selected].id,(minx+maxx)*.5f,render_y,(minz+maxz)*.5f)&&BbMapFeatures::Revealed(areas[selected].id,minx,render_y,minz)&&BbMapFeatures::Revealed(areas[selected].id,maxx,render_y,maxz));};
    auto visible=[&](float minx,float minz,float maxx,float maxz){return on_screen(minx,minz,maxx,maxz)&&revealed_box(minx,minz,maxx,maxz);};
    // The world rectangle under the canvas, for the line grids.
    const float view_x0=cx-canvas_size.x*.5f/zoom-1,view_x1=cx+canvas_size.x*.5f/zoom+1;
    const float view_z0=cz-canvas_size.y*.5f/zoom-1,view_z1=cz+canvas_size.y*.5f/zoom+1;
    // Hatch levels still building get at most this much of a frame; the rest waits for the next.
    const auto build_deadline=std::chrono::steady_clock::now()+std::chrono::microseconds(3000);
    auto build_budget=[&]{return std::max(0.0,std::chrono::duration<double,std::milli>(build_deadline-std::chrono::steady_clock::now()).count());};
    auto outline=[&](const std::vector<Point>& ring,ImU32 color,float width){for(size_t i=0;i<ring.size();++i){const auto a=ring[i],b=ring[(i+1)%ring.size()];if(visible(std::min(a.x,b.x),std::min(a.z,b.z),std::max(a.x,b.x),std::max(a.z,b.z)))draw->AddLine(project(a.x,a.z),project(b.x,b.z),color,width);}};
    if(!available){const char* message=location.valid?"Map data is not available for this location":"Your position is unavailable while loading or outside a supported area";const ImVec2 extent=font->CalcTextSizeA(20*scale,FLT_MAX,0,message);draw->AddText(font,20*scale,ImVec2(canvas_center.x-extent.x*.5f,canvas_center.y-10*scale),muted,message);}
    else {
        auto& a=areas[selected];
        int active=current==selected&&!preview_active?AutoLayer(a):PrimaryLayer(a);
        if(preview_active&&selected_destination>=0&&destinations[selected_destination].area==a.id){const auto saved=location;const auto& d=destinations[selected_destination];location.x=d.x;location.y=d.y;location.z=d.z;active=AutoLayer(a);location=saved;}
        if(active>=0)render_y=a.layers[active].anchor;
        // Reserve actual glyph footprints in screen space as well as excluding
        // collision floors in world space. Transparent icon edges stay clean.
        std::vector<BbAtlasStyle::Box> glyph_masks;
        auto reserveGlyph=[&](float x,float y,float z,float radius,bool all_levels=false){if(!all_levels&&active>=0&&std::abs(y-a.layers[active].anchor)>std::max(6.f,a.layers[active].span*1.4f))return;const auto p=project(x,z);const float r=radius*scale;glyph_masks.push_back({p.x-r,p.y-r,2*r,2*r});};
        for(const auto& lamp:destinations)if(lamp.area==a.id&&lamp.discovered)reserveGlyph(lamp.x,lamp.y,lamp.z,18,true);
        for(const auto& marker:a.markers)reserveGlyph(marker.x,marker.y,marker.z,18);
        if(current==selected&&!preview_active)reserveGlyph(location.x,location.y,location.z,20);
        const auto compass=at(BbAtlasStyle::Layout::compass_x,BbAtlasStyle::Layout::compass_y);glyph_masks.push_back({compass.x-38*scale,compass.y-38*scale,76*scale,76*scale});

        std::vector<std::pair<float,float>> blocked;
        auto scratch=[&](ImVec2 a,ImVec2 b,ImU32 color){
            blocked.clear();const BbAtlasStyle::Point p{a.x,a.y},q{b.x,b.y};
            for(const auto& r:glyph_masks){if(std::max(a.x,b.x)<r.x||std::min(a.x,b.x)>r.x+r.w||std::max(a.y,b.y)<r.y||std::min(a.y,b.y)>r.y+r.h)continue;const std::array<BbAtlasStyle::Point,4> polygon={BbAtlasStyle::Point{r.x,r.y},BbAtlasStyle::Point{r.x+r.w,r.y},BbAtlasStyle::Point{r.x+r.w,r.y+r.h},BbAtlasStyle::Point{r.x,r.y+r.h}};float lo,hi;if(BbAtlasStyle::Clip(polygon,p,q,lo,hi))blocked.emplace_back(lo,hi);}
            std::sort(blocked.begin(),blocked.end());float begin=0;
            auto emit=[&](float lo,float hi){if(hi-lo<.001f)return;const auto u=BbAtlasStyle::Mix(p,q,lo),v=BbAtlasStyle::Mix(p,q,hi);draw->AddLine(ImVec2(u.x,u.z),ImVec2(v.x,v.z),color,std::clamp(.72f*scale,.6f,1.3f));};
            for(const auto& interval:blocked){if(interval.first>begin)emit(begin,interval.first);begin=std::max(begin,interval.second);}if(begin<1)emit(begin,1);
        };
        const ImVec2 texture_origin((a.bounds[0]+a.bounds[2])*.5f,(a.bounds[1]+a.bounds[3])*.5f);
        const float texture_span=std::max(a.bounds[2]-a.bounds[0],a.bounds[3]-a.bounds[1]);
        float height_min=active>=0&&active<int(a.layers.size())?a.layers[active].anchor:location.y-3.0f;
        float height_max=height_min;
        for(size_t li=0;active>=0&&active<int(a.layers.size())&&li<a.layers.size();++li)if(int(li)==active||std::abs(a.layers[li].anchor-a.layers[active].anchor)<=6.0f){
            const auto& layer=a.layers[li];
            const float low=layer.has_vertex_heights?layer.min_y:layer.anchor;
            const float high=layer.has_vertex_heights?layer.max_y:layer.anchor;
            height_min=std::min(height_min,low);height_max=std::max(height_max,high);
        }
        auto heightTint=[&](float y,int alpha){const float t=elevation_shading?std::clamp((y-height_min)/std::max(.01f,height_max-height_min),0.0f,1.0f):.72f;const int shade=int(118+120*t);return IM_COL32(shade+4,shade+2,shade,alpha);};
        auto floorTriangle=[&](const Layer& layer,const Triangle& t,int alpha){
            const float minx=std::min({t.v[0],t.v[2],t.v[4]}),maxx=std::max({t.v[0],t.v[2],t.v[4]}),minz=std::min({t.v[1],t.v[3],t.v[5]}),maxz=std::max({t.v[1],t.v[3],t.v[5]});if(!on_screen(minx,minz,maxx,maxz))return;
            const float fy=layer.has_vertex_heights?(t.y[0]+t.y[1]+t.y[2])/3:layer.anchor;
            if(!BbMapFeatures::Revealed(a.id,(t.v[0]+t.v[2]+t.v[4])/3,fy,(t.v[1]+t.v[3]+t.v[5])/3))return;
            for(int k=0;k<3;++k)if(!BbMapFeatures::Revealed(a.id,t.v[2*k],layer.has_vertex_heights?t.y[k]:layer.anchor,t.v[2*k+1]))return;
            if(!revealed_box(minx,minz,maxx,maxz))return;
            const ImVec2 screen_pts[3]={project(t.v[0],t.v[1]),project(t.v[2],t.v[3]),project(t.v[4],t.v[5])};
            const ImVec2 world_pts[3]={ImVec2(t.v[0],t.v[1]),ImVec2(t.v[2],t.v[3]),ImVec2(t.v[4],t.v[5])};
            const ImU32 colors[3]={heightTint(layer.has_vertex_heights?t.y[0]:layer.anchor,alpha),heightTint(layer.has_vertex_heights?t.y[1]:layer.anchor,alpha),heightTint(layer.has_vertex_heights?t.y[2]:layer.anchor,alpha)};
            if(BbMapArt::IsReady())BbMapArt::DrawFloorTriangle(draw,screen_pts,world_pts,colors,texture_span,texture_origin);
            else draw->AddTriangleFilled(screen_pts[0],screen_pts[1],screen_pts[2],colors[0]);
        };
        // Wall-band strokes exclude all projected floors. Interior fills instead
        // describe a closed gap on a displayed storey. All floors draw above them.
        if(!a.cut_cache.ready){std::vector<BbAtlasStyle::Triangle> floors;for(const auto& layer:a.layers){for(const auto& t:layer.triangles)floors.push_back({{{{t.v[0],t.v[1]},{t.v[2],t.v[3]},{t.v[4],t.v[5]}}}});for(const auto& r:layer.rects){floors.push_back({{{{r.x,r.z},{r.x+r.w,r.z},{r.x,r.z+r.h}}}});floors.push_back({{{{r.x+r.w,r.z},{r.x+r.w,r.z+r.h},{r.x,r.z+r.h}}}});}}a.cut_cache.Build(std::move(floors),a.layers.size());}
        if(!a.interior_cache.ready){
            std::vector<std::vector<BbAtlasInteriors::Ring>> rings;
            for(const auto& layer:a.layers){rings.emplace_back();for(const auto& outline:layer.outlines){BbAtlasInteriors::Ring ring;for(auto p:outline)ring.push_back({p.x,p.z});rings.back().push_back(std::move(ring));}}
            std::vector<BbAtlasStyle::FloorIndex> layer_floors(a.layers.size());
            for(size_t li=0;li<a.layers.size();++li){std::vector<BbAtlasStyle::Triangle> floors;for(const auto& t:a.layers[li].triangles)floors.push_back({{{{t.v[0],t.v[1]},{t.v[2],t.v[3]},{t.v[4],t.v[5]}}}});for(const auto& r:a.layers[li].rects){floors.push_back({{{{r.x,r.z},{r.x+r.w,r.z},{r.x,r.z+r.h}}}});floors.push_back({{{{r.x+r.w,r.z},{r.x+r.w,r.z+r.h},{r.x,r.z+r.h}}}});}layer_floors[li].Build(std::move(floors));}
            a.interior_cache.Build(rings,layer_floors);
        }
        const int interior_lod=BbAtlasStyle::CutCache::Level(zoom,scale);
        // Context interiors first, then the current storey's stronger material.
        // Every floor is painted afterward, so a void on another storey can
        // never hide the current floor or remove faded other-level context.
        for(int pass=0;pass<2;++pass)for(size_t li=0;li<a.interior_cache.layers.size();++li){
            if((int(li)==active)!=(pass==1))continue;
            for(const auto& t:a.interior_cache.layers[li]){
                const auto& p=t.p;if(!visible(std::min({p[0].x,p[1].x,p[2].x}),std::min({p[0].z,p[1].z,p[2].z}),std::max({p[0].x,p[1].x,p[2].x}),std::max({p[0].z,p[1].z,p[2].z})))continue;
                // A closed hole in this storey, not a globally blocked building.
                draw->AddTriangleFilled(project(p[0].x,p[0].z),project(p[1].x,p[1].z),project(p[2].x,p[2].z),pass==1?IM_COL32(53,48,39,255):IM_COL32(44,41,34,255));
            }
        }
        for(size_t li=0;li<a.interior_cache.layers.size();++li){
            // A level still building shows the nearest finished one; nothing until one exists.
            if(!a.interior_cache.Ready(li,interior_lod))a.interior_cache.Step(li,interior_lod,build_budget());
            const int lod=a.interior_cache.NearestReady(li,interior_lod);if(lod<0)continue;
            LinesInView(a.interior_cache.Get(li,lod),view_x0,view_z0,view_x1,view_z1,[&](const BbAtlasStyle::Line& line){
                if(!visible(std::min(line.a.x,line.b.x),std::min(line.a.z,line.b.z),std::max(line.a.x,line.b.x),std::max(line.a.z,line.b.z)))return;
                scratch(project(line.a.x,line.a.z),project(line.b.x,line.b.z),IM_COL32(135,119,90,int(li)==active?28+line.wear%20:15+line.wear%13));
            });
        }
        // Keep the whole area's other storeys as subdued context. A narrow
        // height window hid the streets below bridges and made orientation
        // difficult. Context draws above all enclosed interiors; active floor stays opaque.
        for(size_t li=0;li<a.layers.size();++li)if(int(li)!=active&&active>=0){
            const auto& layer=a.layers[li];
            render_y=layer.anchor;
            const bool nearby=std::abs(layer.anchor-a.layers[active].anchor)<=6.0f;
            const int alpha=nearby?38:27;
            for(const auto& t:layer.triangles)floorTriangle(layer,t,alpha);
            for(const auto& r:layer.rects)if(visible(r.x,r.z,r.x+r.w,r.z+r.h))draw->AddRectFilled(project(r.x,r.z+r.h),project(r.x+r.w,r.z),heightTint(layer.anchor,alpha));
            for(const auto& ring:layer.outlines)outline(ring,IM_COL32(213,203,177,nearby?62:49),.7f*scale);
        }
        if(active>=0&&active<int(a.layers.size())){
            render_y=a.layers[active].anchor;

            const int wanted=BbAtlasStyle::CutCache::Level(zoom,scale);
            if(!a.cut_cache.layers[active][wanted].built){
                std::vector<BbAtlasStyle::Line> wall_support;for(const auto& w:a.layers[active].walls)wall_support.push_back({{w.a.x,w.a.z},{w.b.x,w.b.z}});
                a.cut_cache.Step(active,wanted,wall_support,build_budget());
            }
            auto draw_hatch=[&](const BbAtlasStyle::Line& hatch){
                if(!visible(std::min(hatch.a.x,hatch.b.x),std::min(hatch.a.z,hatch.b.z),std::max(hatch.a.x,hatch.b.x),std::max(hatch.a.z,hatch.b.z)))return;
                // Deterministic worn opacity, never random or frame dependent.
                const int alpha=23+int(hatch.wear%30);scratch(project(hatch.a.x,hatch.a.z),project(hatch.b.x,hatch.b.z),IM_COL32(166,160,143,alpha));
            };
            // While the wanted level builds: the nearest finished one, else the strokes made so far.
            const int lod=a.cut_cache.NearestBuilt(active,wanted);
            if(lod>=0)LinesInView(a.cut_cache.layers[active][lod].strokes,view_x0,view_z0,view_x1,view_z1,draw_hatch);
            else for(const auto& hatch:a.cut_cache.layers[active][wanted].strokes)draw_hatch(hatch);
        }
        if(active>=0&&active<int(a.layers.size())){
            const auto& layer=a.layers[active];for(const auto& t:layer.triangles)floorTriangle(layer,t,255);
            for(const auto& r:layer.rects)if(visible(r.x,r.z,r.x+r.w,r.z+r.h))draw->AddRectFilled(project(r.x,r.z+r.h),project(r.x+r.w,r.z),heightTint(layer.anchor,255));
            for(const auto& ring:layer.outlines)outline(ring,IM_COL32(204,193,163,220),.85f*scale);
            const float wall=std::clamp(zoom*.13f,2.5f*scale,5.0f*scale);for(const auto& w:layer.walls)if(visible(std::min(w.a.x,w.b.x),std::min(w.a.z,w.b.z),std::max(w.a.x,w.b.x),std::max(w.a.z,w.b.z)))draw->AddLine(project(w.a.x,w.a.z),project(w.b.x,w.b.z),IM_COL32(15,18,19,255),wall);
        }
        const float marker_height=active>=0?a.layers[active].span:6.0f;
        auto marker=[&](float x,float y,float z,const std::string& kind,const std::string& name){const auto p=project(x,z);if(p.x<origin.x-22*scale||p.y<origin.y-22*scale||p.x>origin.x+canvas_size.x+22*scale||p.y>origin.y+canvas_size.y+22*scale)return;if(active>=0&&std::abs(y-a.layers[active].anchor)>std::max(6.0f,marker_height*1.4f))return;const char* icon=kind=="lamp"?"lamp":kind=="ladder"?"ladder":kind=="gate"?"gate":"talk";BbMapArt::DrawIcon(draw,icon,p,32.0f*scale);if(hovered&&std::hypot(ImGui::GetIO().MousePos.x-p.x,ImGui::GetIO().MousePos.y-p.y)<18.0f*scale){if(kind=="gate")ImGui::SetTooltip("%s\nOpenable gate / door\nMay require unlocking; status is not tracked.",name.c_str());else ImGui::SetTooltip("%s",name.c_str());}};
        for(size_t i=0;i<destinations.size();++i) {
            const auto& d=destinations[i];if(d.area!=a.id)continue;
            // Lamps are destinations across all displayed storeys. Filtering by
            // the player's floor hid Tomb of Oedon below Central Yharnam.
            if(!BbAtlasStyle::Layout::LampOnMap(d.area==a.id,d.discovered))continue;
            const auto p=project(d.x,d.z);if(p.x<origin.x||p.y<origin.y||p.x>origin.x+canvas_size.x||p.y>origin.y+canvas_size.y)continue;
            drawn_lamps.push_back({{"name",d.name},{"available",d.available},{"x",p.x},{"y",p.y}});
            const bool pointer_near=std::hypot(pointer.x-p.x,pointer.y-p.y)<20*scale;
            if(d.available&&(selected_destination==int(i)||pointer_near))draw->AddCircle(p,20*scale,IM_COL32(233,206,143,220),32,1.5f*scale);
            BbMapArt::DrawIcon(draw,"lamp",p,32*scale,0,d.available?IM_COL32_WHITE:IM_COL32(100,100,100,125));
            if((pointer_near || (confirm&&selected_destination==int(i)))&&!dialog_was_open&&(UsesControllerGlyphs()||hovered||confirm)) {
                if(UsesControllerGlyphs())ImGui::SetNextWindowPos(ImVec2(pointer.x+22*scale,pointer.y+18*scale));
                ImGui::SetTooltip("%s\n%s",d.name.c_str(),d.available?(BbMapFeatures::TravelEnabled()?"Select to travel":"Map fast travel is disabled in the launcher"):"Locked or currently unavailable");
                if(BbMapFeatures::TravelEnabled()&&d.available&&(confirm||(!UsesControllerGlyphs()&&ImGui::IsMouseReleased(ImGuiMouseButton_Left)&&!map_dragged))){selected_destination=int(i);travel_dialog=int(i);ImGui::OpenPopup("Travel to lamp");}
            }
        }
        for(const auto& m:a.markers)if(BbMapFeatures::Revealed(a.id,m.x,m.y,m.z)&&(m.kind!="npc"||BbMapFeatures::NpcVisible(a.id,m.entity)))marker(m.x,m.y,m.z,m.kind,m.name);
        for(const auto& pickup:BbMapFeatures::Pickups(a.id)) {
            if(active>=0&&std::abs(pickup.y-a.layers[active].anchor)>std::max(3.f,a.layers[active].span))continue;
            const auto p=project(pickup.x,pickup.z);if(p.x<origin.x||p.y<origin.y||p.x>origin.x+canvas_size.x||p.y>origin.y+canvas_size.y)continue;
            const ImU32 color=pickup.category=="healing"?IM_COL32(230,81,76,255):pickup.category=="insight"?IM_COL32(189,121,234,255):pickup.category=="equipment"?IM_COL32(93,172,242,255):IM_COL32(235,193,79,255);
            draw->AddCircleFilled(p,4.1f*scale,IM_COL32(20,22,24,255),12);draw->AddCircleFilled(p,3.f*scale,color,12);
            if(!dialog_was_open&&std::hypot(pointer.x-p.x,pointer.y-p.y)<9*scale)ImGui::SetTooltip("%s",pickup.label.c_str());
        }
        if(UsesControllerGlyphs()&&BbMapFeatures::TravelEnabled()){draw->AddCircle(pointer,8*scale,paper,24,1.f*scale);draw->AddLine(ImVec2(pointer.x-13*scale,pointer.y),ImVec2(pointer.x+13*scale,pointer.y),paper,.7f*scale);draw->AddLine(ImVec2(pointer.x,pointer.y-13*scale),ImVec2(pointer.x,pointer.y+13*scale),paper,.7f*scale);}
        if(current==selected&&!preview_active){const auto p=project(location.x,location.z);const auto dir=FacingOnMap(location.yaw);const float angle=std::atan2(dir.x,-dir.y);draw->AddCircleFilled(p,18.5f*scale,IM_COL32(96,139,138,27),32);draw->AddCircleFilled(p,16.0f*scale,IM_COL32(20,29,29,210),32);draw->AddCircle(p,17.0f*scale,IM_COL32(125,160,155,120),32,.8f*scale);BbMapArt::DrawIcon(draw,"player",p,BbAtlasStyle::Layout::player_size*scale,angle,IM_COL32(178,206,200,230));}
    }
    // Restore the same background texture at all four edges. Matching UVs
    // preserve the painting; nonoverlapping corner wedges avoid dark seams.
    BbMapArt::DrawBackgroundFade(draw,screen,ImVec2(screen.x+full.x,screen.y+full.y),origin,ImVec2(origin.x+canvas_size.x,origin.y+canvas_size.y),BbAtlasStyle::Layout::edge_fade*scale);
    draw->PopClipRect();
    for(float x:{230.f,1065.f}){
        draw->AddLine(at(x,123),at(x,643),IM_COL32(154,144,119,76),.65f*scale);
        draw->AddLine(at(x-2,145),at(x-2,621),IM_COL32(112,107,91,35),.5f*scale);
        ornament(x,123,3,IM_COL32(154,144,119,95));ornament(x,643,3,IM_COL32(154,144,119,95));
    }
    BbMapArt::DrawIcon(draw,"compass",at(BbAtlasStyle::Layout::compass_x,BbAtlasStyle::Layout::compass_y),BbAtlasStyle::Layout::compass_size*scale,0,IM_COL32(174,166,143,170));
    // Stack keys in the right artwork gutter, aligned to the material key.
    if(available){
        constexpr float x=BbAtlasStyle::Layout::key_x;
        float bottom=BbAtlasStyle::Layout::key_y;
        const char* labels[]={"Floor","Other levels","Interior"};
        const ImU32 colors[]={IM_COL32(207,204,196,255),IM_COL32(70,70,63,255),IM_COL32(53,48,39,255)};
        draw->AddLine(at(x,bottom-8),at(x+BbAtlasStyle::Layout::key_w,bottom-8),rule,.6f*scale);
        for(int i=0;i<3;++i){const float row=bottom+i*18;draw->AddRectFilled(at(x,row+2),at(x+13,row+13),colors[i]);draw->AddRect(at(x,row+2),at(x+13,row+13),rule,0,0,.6f*scale);draw->AddText(font,13*scale,at(x+20,row-1),muted,labels[i]);}
        bottom-=20;
        if(elevation_shading){
            const float top=bottom-86;
            draw->AddRectFilledMultiColor(at(x,top),at(x+13,bottom),IM_COL32(225,220,202,195),IM_COL32(225,220,202,195),IM_COL32(52,55,51,195),IM_COL32(52,55,51,195));
            draw->AddRect(at(x,top),at(x+13,bottom),rule,0,0,.8f*scale);
            draw->AddText(font,13*scale,at(x+20,top-2),muted,"High");draw->AddText(font,13*scale,at(x+20,bottom-15),muted,"Low");bottom=top-24;
        }
        struct Key {const char* category;const char* label;ImU32 color;};
        const Key keys[]={{"healing","Blood vials",IM_COL32(230,81,76,255)},{"insight","Insight",IM_COL32(189,121,234,255)},
                          {"equipment","Equipment",IM_COL32(93,172,242,255)},{"echoes","Coldblood",IM_COL32(235,193,79,255)}};
        int count=0;for(const auto& k:keys)if(BbMapFeatures::ItemCategoryEnabled(k.category))++count;
        if(count){float row=bottom-18*count;draw->AddText(font,12*scale,at(x,row-20),muted,"Pickups");
            for(const auto& k:keys)if(BbMapFeatures::ItemCategoryEnabled(k.category)){const auto dot=at(x+6,row+7);draw->AddCircleFilled(dot,3*scale,k.color,12);draw->AddText(font,13*scale,at(x+20,row-1),paper,k.label);row+=18;}}
    }
    draw->AddLine(at(152,BbAtlasStyle::Layout::footer_rule),at(1116,BbAtlasStyle::Layout::footer_rule),rule,.8f*scale);ornament(157,659,3,rule);ornament(1111,659,3,rule);
    const bool controller=UsesControllerGlyphs(),cancel_cross=runtime_map_confirm_button()==0x2000u;
    if(travel_dialog>=0&&travel_dialog<int(destinations.size())) {
        // Use explicit draw-list text and hit boxes: the port's global overlay
        // font multiplier must not scale a second time at 1440p or 4K.
        const auto box=layout.TravelDialog();
        ImGui::SetNextWindowPos(ImVec2(box.x,box.y),ImGuiCond_Always);
        ImGui::SetNextWindowSize(ImVec2(box.w,box.h),ImGuiCond_Always);
        ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding,ImVec2(0,0));
        ImGui::PushStyleVar(ImGuiStyleVar_WindowRounding,3*scale);
        ImGui::PushStyleVar(ImGuiStyleVar_WindowBorderSize,1*scale);
        ImGui::PushStyleColor(ImGuiCol_PopupBg,IM_COL32(27,29,27,250));
        ImGui::PushStyleColor(ImGuiCol_Border,IM_COL32(152,146,128,210));
        ImGui::PushStyleColor(ImGuiCol_ModalWindowDimBg,IM_COL32(0,0,0,110));
        ImGui::OpenPopup("Travel to lamp");
        if(ImGui::BeginPopupModal("Travel to lamp",nullptr,ImGuiWindowFlags_NoTitleBar|ImGuiWindowFlags_NoMove|ImGuiWindowFlags_NoResize|ImGuiWindowFlags_NoSavedSettings|ImGuiWindowFlags_NoScrollbar|ImGuiWindowFlags_NoScrollWithMouse)) {
            auto* dialog=ImGui::GetWindowDrawList();
            auto point=[&](float x,float y){return ImVec2(box.x+x*scale,box.y+y*scale);};
            dialog->AddText(font,19*scale,point(20,13),paper,"Travel to lamp");
            dialog->AddLine(point(20,43),point(330,43),rule,scale);
            const auto& d=destinations[travel_dialog];
            // Travel starts only over the game's quick menu (runtime_atlas_travel_request): a map
            // opened with its key during play showed Travel and then refused it as "the
            // destination changed" (#207), so say where travel works instead.
            BbMapMenu travel_menu{};
            const bool from_menu=runtime_map_menu_state(&travel_menu)&&travel_menu.top_level;
            const bool lamp_ok=d.available&&BbMapFeatures::TravelEnabled()&&runtime_atlas_travel_supported();
            const bool ready=!cancel_dialog&&lamp_ok&&from_menu;
            std::string message=ready?"Travel to "+d.name+"?":lamp_ok?
                "Travel works from the game menu: press "+std::string(controller?"Options / Menu":"Esc")+", then choose Map.":
                "This lamp is currently unavailable.";
            dialog->AddText(font,17*scale,point(20,57),paper,message.c_str(),nullptr,310*scale);
            auto button=[&](const char* id,const char* text,float x,bool enabled){
                ImGui::SetCursorScreenPos(point(x,116));ImGui::BeginDisabled(!enabled);
                bool pressed=ImGui::InvisibleButton(id,ImVec2(146*scale,34*scale));
                const bool hover=ImGui::IsItemHovered();ImGui::EndDisabled();
                dialog->AddRectFilled(point(x,116),point(x+146,150),hover?IM_COL32(103,91,63,255):IM_COL32(63,60,46,255),2*scale);
                dialog->AddRect(point(x,116),point(x+146,150),enabled?rule:IM_COL32(80,80,75,150),2*scale,0,scale);
                const auto extent=font->CalcTextSizeA(16*scale,FLT_MAX,0,text);
                dialog->AddText(font,16*scale,ImVec2(box.x+(x+73)*scale-extent.x*.5f,box.y+123*scale),enabled?paper:muted,text);
                return pressed;
            };
            if((button("travel-confirm","Travel",20,ready)||(confirm&&dialog_was_open))&&ready){
                if(runtime_atlas_travel_request(&d.native)){travel_monitor=true;travel_message.clear();travel_dialog=-1;ImGui::CloseCurrentPopup();Close();}
                else travel_message="The destination changed or the game cannot travel now.";
            }
            if(button("travel-cancel","Cancel",184,true)||cancel_dialog){travel_dialog=-1;ImGui::CloseCurrentPopup();}
            ImGui::EndPopup();
        }
        ImGui::PopStyleColor(3);ImGui::PopStyleVar(3);
    }
    if(!travel_message.empty())draw->AddText(font,14*scale,at(175,634),paper,travel_message.c_str());
    if(!BbMapFeatures::Error().empty())draw->AddText(font,12*scale,at(175,614),muted,BbMapFeatures::Error().c_str());
    const bool ps=BbAtlasMenu::UsesPlayStationGlyphs();
    struct Control {const char* label;const char* key;const char* icon;int action;};
    std::vector<Control> controls;
    if(BbMapFeatures::TravelEnabled()){
        controls.push_back({"Lamps",controller?(ps?"L1/R1":"LB/RB"):"Q/E",nullptr,1});
        if(controller)controls.push_back({"Pointer","LS",nullptr,0});
    }
    controls.push_back({"Pan",controller?"RS":"Drag",nullptr,0});
    controls.push_back({"Zoom",controller?(ps?"L2/R2":"LT/RT"):"-/+",nullptr,2});
    controls.push_back({"Recenter",controller?(ps?"Triangle":"Y"):"Home",controller&&!ps?"Y":nullptr,3});
    if(BbMapFeatures::TravelEnabled())controls.push_back({"Travel",controller?(ps?(cancel_cross?"Circle":"Cross"):(cancel_cross?"B":"A")):"Click",nullptr,4});
    controls.push_back({"Back",controller?(ps?(cancel_cross?"Cross":"Circle"):(cancel_cross?"A":"B")):"Esc",controller&&!ps&&!cancel_cross?"B":nullptr,5});
    for(size_t i=0;i<controls.size();++i){
        const auto& c=controls[i];const auto box=layout.FooterSlot(int(i),int(controls.size()));
        const float label_font=16*scale,key_font=12*scale;
        const auto text=font->CalcTextSizeA(label_font,FLT_MAX,0,c.label),key=font->CalcTextSizeA(key_font,FLT_MAX,0,c.key);
        const float glyph=c.icon?24*scale:key.x+10*scale;
        const float px=box.x+(box.w-glyph-6*scale-text.x)*.5f;
        if(i)draw->AddLine(ImVec2(box.x,box.y+5*scale),ImVec2(box.x,box.y+28*scale),rule,.7f*scale);
        ImGui::SetCursorScreenPos(ImVec2(box.x+3*scale,box.y));ImGui::PushID(int(i));
        if(ImGui::InvisibleButton("footer",ImVec2(box.w-6*scale,box.h))&&!dialog_was_open){
            if(c.action==1)cycle_request=ImGui::GetIO().MousePos.x>box.x+box.w*.5f?1:-1;
            if(c.action==2)zoom=std::clamp(zoom*(ImGui::GetIO().MousePos.x>box.x+box.w*.5f?1.25f:.8f),.15f*scale,25.f*scale);
            if(c.action==3)Recenter();
            if(c.action==4&&selected_destination>=0&&destinations[selected_destination].available)travel_dialog=selected_destination;
            if(c.action==5)Close();
        }
        if(ImGui::IsItemHovered()){
            draw->AddLine(ImVec2(box.x+8*scale,box.y+box.h),ImVec2(box.x+box.w-8*scale,box.y+box.h),rule,.8f*scale);
            if(c.action==0)ImGui::SetTooltip("%s",c.label==std::string("Pointer")?"Move the left stick to point at a lamp.":controller?"Move the right stick to pan.":"Drag the map to pan.");
        }
        ImGui::PopID();
        if(c.icon)BbMapArt::DrawIcon(draw,c.icon,ImVec2(px+12*scale,box.y+17*scale),24*scale);
        else{draw->AddRect(ImVec2(px,box.y+5*scale),ImVec2(px+glyph,box.y+28*scale),rule,2*scale,0,.7f*scale);draw->AddText(font,key_font,ImVec2(px+5*scale,box.y+9*scale),muted,c.key);}
        draw->AddText(font,label_font,ImVec2(px+glyph+6*scale,box.y+6*scale),paper,c.label);
    }
    if(const char* qa=std::getenv("BB_ATLAS_QA");qa&&std::string(qa)=="1"){
        const auto dialog=layout.TravelDialog();Json footer=Json::array();
        for(const auto& c:controls)footer.push_back(c.label);
        qa_layout={{"scale",scale},{"width",full.x},{"height",full.y},{"footer",footer},
            {"lamps",drawn_lamps},{"dialog",{dialog.x,dialog.y,dialog.w,dialog.h}},
            {"dialog_visible",dialog_was_open},{"dialog_body_font",17*scale},{"legend_x",layout.At(BbAtlasStyle::Layout::key_x,0).x}};
    }
    ImGui::End();
}
}
