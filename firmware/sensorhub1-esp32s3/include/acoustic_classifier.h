#pragma once

#include <Arduino.h>

namespace zeep {

struct AcousticFeatures {
  bool ready = false;
  bool valid = false;
  const char* label = "unknown";
  float confidence = 0.0F;
  float low_band_ratio = NAN;
  float mid_band_ratio = NAN;
  float high_band_ratio = NAN;
  float spectral_centroid_hz = NAN;
  float spectral_flatness = NAN;
  float spectral_flux = NAN;
  float crest_factor = NAN;
  float syllabic_modulation = NAN;
  float breathing_periodicity = NAN;
  float breathing_period_s = NAN;
  uint16_t spectral_frames = 0;
  uint16_t envelope_frames = 0;
  bool event_detected = false;
  const char* model_version = "zeep-dsp-rule-v0.1-shadow";
};

class AcousticClassifier {
 public:
  void reset();
  void addSample(float normalized_sample, float dc_blocked_sample);
  AcousticFeatures finish(float laeq_dba, float rms, float peak);

 private:
  void addEnvelopeSample(float sample);
  void addSpectrumSample(float sample);
  void analyseSpectrumFrame();

  static constexpr size_t kFftSize = 512;
  static constexpr size_t kEnvelopeSize = 200;
  static constexpr uint32_t kEnvelopeSamples = 2400;  // 50 ms at 48 kHz.

  float fft_real_[kFftSize] = {};
  float fft_imag_[kFftSize] = {};
  float previous_magnitude_[kFftSize / 2 + 1] = {};
  float envelope_[kEnvelopeSize] = {};
  size_t fft_index_ = 0;
  size_t envelope_index_ = 0;
  uint32_t decimation_counter_ = 0;
  uint32_t envelope_samples_ = 0;
  double envelope_sum_square_ = 0.0;
  double low_energy_ = 0.0;
  double mid_energy_ = 0.0;
  double high_energy_ = 0.0;
  double centroid_weighted_ = 0.0;
  double centroid_energy_ = 0.0;
  double flatness_sum_ = 0.0;
  double flux_sum_ = 0.0;
  uint16_t spectral_frames_ = 0;
  bool have_previous_spectrum_ = false;
};

}  // namespace zeep
