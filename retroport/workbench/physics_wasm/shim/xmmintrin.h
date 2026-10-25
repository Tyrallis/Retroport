// WebAssembly has no SSE. The engine uses only the scalar estimates rsqrtss and rcpss (to match the
// retail client's x86 code): here they are exact, which differs from the hardware estimate by less
// than 1/4096 - nothing a preview can show.
#pragma once
#include <cmath>

typedef struct { float f; } __m128;
static inline __m128 _mm_set_ss(float x) { return __m128{x}; }
static inline float _mm_cvtss_f32(__m128 a) { return a.f; }
static inline __m128 _mm_rsqrt_ss(__m128 a) { return __m128{1.0f / std::sqrt(a.f)}; }
static inline __m128 _mm_rcp_ss(__m128 a) { return __m128{1.0f / a.f}; }
