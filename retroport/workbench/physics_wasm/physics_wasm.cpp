// The preview's physics: Equip Plus's copy of Kirazul's port of retail's engine
// (physics_domino.*, not covered by the workbench's licence; see README.md), behind a small C
// interface for the browser. Built to physics.wasm by build.py.
//
// One handle per simulated model: the row it was made from and its engine instance.

#include "physics_domino.h"

#include <cstdint>
#include <cstdlib>
#include <new>

namespace phys = wow::ec::physics;

namespace
{
    struct Handle
    {
        phys::Model     model;
        phys::Instance* sim = nullptr;
    };
}

extern "C" {

__attribute__((export_name("ph_alloc"))) void* ph_alloc(uint32_t size) { return std::malloc(size); }
__attribute__((export_name("ph_free"))) void ph_free(void* p) { std::free(p); }

/// A simulation of the row keyed `model.m2` in a PHY2 table; null when it has none.
__attribute__((export_name("ph_create"))) Handle* ph_create(const uint8_t* table, uint32_t size)
{
    Handle* h = new (std::nothrow) Handle();
    if (!h) return nullptr;
    if (!phys::Find(table, size, "model.m2", h->model) || h->model.bodies.empty())
    {
        delete h;
        return nullptr;
    }
    h->sim = new (std::nothrow) phys::Instance(&h->model);
    if (!h->sim)
    {
        delete h;
        return nullptr;
    }
    return h;
}

__attribute__((export_name("ph_destroy"))) void ph_destroy(Handle* h)
{
    if (!h) return;
    delete h->sim;
    delete h;
}

__attribute__((export_name("ph_bodies"))) uint32_t ph_bodies(const Handle* h)
{
    return h ? uint32_t(h->model.bodies.size()) : 0;
}

/// The bone body `i` drives (0xFFFF for none).
__attribute__((export_name("ph_body_bone"))) uint32_t ph_body_bone(const Handle* h, uint32_t i)
{
    return h && i < h->model.bodies.size() ? h->model.bodies[i].bone : 0xFFFF;
}

/// One frame: `bone_world` n column-form matrices (row major, m[r*4+c]) taking a model point to the
/// world, `pivots` n x 3 floats, `placement` the model's own column-form matrix, `dt` seconds.
__attribute__((export_name("ph_step"))) void ph_step(Handle* h, const double* bone_world, const float* pivots,
                                                      uint32_t n, const double* placement, float dt)
{
    if (!h || !h->sim) return;
    phys::Frame f;
    f.boneWorld = reinterpret_cast<const double (*)[16]>(bone_world);
    f.pivots    = reinterpret_cast<const phys::V3*>(pivots);
    f.boneCount = n;
    for (int k = 0; k < 16; ++k) f.placement[k] = placement[k];
    f.dt = dt;
    h->sim->Step(f);
}

/// Body `i`'s bone in model space (column form), or 0 for a body that writes none.
__attribute__((export_name("ph_output"))) int ph_output(const Handle* h, uint32_t i, double* out)
{
    return h && h->sim && h->sim->Output(i, out) ? 1 : 0;
}

}
