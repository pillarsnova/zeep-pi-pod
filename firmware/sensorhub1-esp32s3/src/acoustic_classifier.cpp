#include "acoustic_classifier.h"

#include <algorithm>
#include <cmath>

namespace zeep {

namespace {

constexpr float kPi = 3.14159265358979323846F;
constexpr float kSpectrumSampleRateHz = 12000.0F;
constexpr float kEpsilon = 1.0e-12F;

float clamp01(float value) {
  return std::max(0.0F, std::min(1.0F, value));
}

void fft(float* real, float* imaginary, size_t size) {
  for (size_t index = 1, reversed = 0; index < size; ++index) {
    size_t bit = size >> 1;
    for (; reversed & bit; bit >>= 1) {
      reversed ^= bit;
    }
    reversed ^= bit;
    if (index < reversed) {
      std::swap(real[index], real[reversed]);
      std::swap(imaginary[index], imaginary[reversed]);
    }
  }
  for (size_t length = 2; length <= size; length <<= 1) {
    const float angle = -2.0F * kPi / static_cast<float>(length);
    const float root_real = std::cos(angle);
    const float root_imaginary = std::sin(angle);
    for (size_t offset = 0; offset < size; offset += length) {
      float phase_real = 1.0F;
      float phase_imaginary = 0.0F;
      for (size_t step = 0; step < length / 2; ++step) {
        const size_t even = offset + step;
        const size_t odd = even + length / 2;
        const float odd_real = real[odd] * phase_real -
                               imaginary[odd] * phase_imaginary;
        const float odd_imaginary = real[odd] * phase_imaginary +
                                    imaginary[odd] * phase_real;
        real[odd] = real[even] - odd_real;
        imaginary[odd] = imaginary[even] - odd_imaginary;
        real[even] += odd_real;
        imaginary[even] += odd_imaginary;
        const float next_real = phase_real * root_real -
                                phase_imaginary * root_imaginary;
        phase_imaginary = phase_real * root_imaginary +
                          phase_imaginary * root_real;
        phase_real = next_real;
      }
    }
  }
}

float envelopeBandRatio(const float* envelope, size_t size, float low_hz,
                        float high_hz) {
  if (size < 40) {
    return 0.0F;
  }
  double total = 0.0;
  double selected = 0.0;
  double mean = 0.0;
  for (size_t index = 0; index < size; ++index) {
    mean += envelope[index];
  }
  mean /= size;
  for (size_t bin = 1; bin <= size / 2; ++bin) {
    const float frequency = 20.0F * static_cast<float>(bin) /
                            static_cast<float>(size);
    double real = 0.0;
    double imaginary = 0.0;
    for (size_t index = 0; index < size; ++index) {
      const float angle = 2.0F * kPi * static_cast<float>(bin * index) /
                          static_cast<float>(size);
      const double value = envelope[index] - mean;
      real += value * std::cos(angle);
      imaginary -= value * std::sin(angle);
    }
    const double power = real * real + imaginary * imaginary;
    total += power;
    if (frequency >= low_hz && frequency <= high_hz) {
      selected += power;
    }
  }
  return total > kEpsilon ? static_cast<float>(selected / total) : 0.0F;
}

void breathingPeriodicity(const float* envelope, size_t size,
                          float* best_correlation, float* best_period_s) {
  *best_correlation = 0.0F;
  *best_period_s = NAN;
  if (size < 120) {
    return;
  }
  double mean = 0.0;
  for (size_t index = 0; index < size; ++index) {
    mean += envelope[index];
  }
  mean /= size;
  for (size_t lag = 40; lag <= 120 && lag < size; ++lag) {
    double numerator = 0.0;
    double left_energy = 0.0;
    double right_energy = 0.0;
    for (size_t index = lag; index < size; ++index) {
      const double left = envelope[index] - mean;
      const double right = envelope[index - lag] - mean;
      numerator += left * right;
      left_energy += left * left;
      right_energy += right * right;
    }
    const double denominator = std::sqrt(left_energy * right_energy);
    const float correlation = denominator > kEpsilon
        ? static_cast<float>(numerator / denominator) : 0.0F;
    if (correlation > *best_correlation) {
      *best_correlation = correlation;
      *best_period_s = static_cast<float>(lag) / 20.0F;
    }
  }
}

}  // namespace

void AcousticClassifier::reset() {
  fft_index_ = 0;
  envelope_index_ = 0;
  decimation_counter_ = 0;
  decimation_sum_ = 0.0;
  envelope_samples_ = 0;
  envelope_sum_square_ = 0.0;
  low_energy_ = mid_energy_ = high_energy_ = 0.0;
  centroid_weighted_ = centroid_energy_ = 0.0;
  flatness_sum_ = flux_sum_ = 0.0;
  spectral_frames_ = 0;
  transient_count_ = 0;
  have_previous_spectrum_ = false;
  std::fill(
      previous_magnitude_,
      previous_magnitude_ + kFftSize / 2 + 1,
      0.0F);
}

void AcousticClassifier::addSample(float normalized_sample,
                                   float dc_blocked_sample) {
  addEnvelopeSample(normalized_sample);
  decimation_sum_ += dc_blocked_sample;
  if (++decimation_counter_ >= 4) {
    decimation_counter_ = 0;
    // A four-sample boxcar reduces high-frequency aliasing before the
    // 48 kHz stream is decimated to the 12 kHz classifier stream.
    addSpectrumSample(static_cast<float>(decimation_sum_ / 4.0));
    decimation_sum_ = 0.0;
  }
}

void AcousticClassifier::addEnvelopeSample(float sample) {
  envelope_sum_square_ += static_cast<double>(sample) * sample;
  if (++envelope_samples_ < kEnvelopeSamples) {
    return;
  }
  if (envelope_index_ < kEnvelopeSize) {
    envelope_[envelope_index_++] = static_cast<float>(
        std::sqrt(envelope_sum_square_ / envelope_samples_));
  }
  envelope_samples_ = 0;
  envelope_sum_square_ = 0.0;
}

void AcousticClassifier::addSpectrumSample(float sample) {
  const float window = 0.5F - 0.5F * std::cos(
      2.0F * kPi * static_cast<float>(fft_index_) /
      static_cast<float>(kFftSize - 1));
  fft_real_[fft_index_] = sample * window;
  fft_imag_[fft_index_] = 0.0F;
  if (++fft_index_ >= kFftSize) {
    analyseSpectrumFrame();
    fft_index_ = 0;
  }
}

void AcousticClassifier::analyseSpectrumFrame() {
  fft(fft_real_, fft_imag_, kFftSize);
  double frame_energy = 0.0;
  double frame_weighted = 0.0;
  double log_power = 0.0;
  double arithmetic_power = 0.0;
  double frame_flux = 0.0;
  size_t bins = 0;
  for (size_t bin = 1; bin <= kFftSize / 2; ++bin) {
    const float frequency = kSpectrumSampleRateHz * bin / kFftSize;
    const float power = fft_real_[bin] * fft_real_[bin] +
                        fft_imag_[bin] * fft_imag_[bin] + kEpsilon;
    const float magnitude = std::sqrt(power);
    if (frequency < 300.0F) {
      low_energy_ += power;
    } else if (frequency < 3000.0F) {
      mid_energy_ += power;
    } else {
      high_energy_ += power;
    }
    frame_energy += power;
    frame_weighted += frequency * power;
    arithmetic_power += power;
    log_power += std::log(power);
    if (have_previous_spectrum_) {
      const float change = std::max(0.0F, magnitude - previous_magnitude_[bin]);
      frame_flux += change * change;
    }
    previous_magnitude_[bin] = magnitude;
    ++bins;
  }
  centroid_weighted_ += frame_weighted;
  centroid_energy_ += frame_energy;
  if (bins && arithmetic_power > kEpsilon) {
    const double geometric = std::exp(log_power / bins);
    flatness_sum_ += geometric / (arithmetic_power / bins);
  }
  if (have_previous_spectrum_ && frame_energy > kEpsilon) {
    const float normalized_flux = std::sqrt(frame_flux / frame_energy);
    flux_sum_ += normalized_flux;
    if (normalized_flux >= 0.12F) {
      ++transient_count_;
    }
  }
  have_previous_spectrum_ = true;
  ++spectral_frames_;
}

AcousticFeatures AcousticClassifier::finish(float laeq_dba, float rms,
                                            float peak) {
  AcousticFeatures result;
  result.ready = true;
  result.spectral_frames = spectral_frames_;
  result.envelope_frames = static_cast<uint16_t>(envelope_index_);
  result.transient_count = transient_count_;
  const double total_energy = low_energy_ + mid_energy_ + high_energy_;
  if (spectral_frames_ < 10 || envelope_index_ < 120 ||
      !std::isfinite(laeq_dba) || total_energy <= kEpsilon) {
    return result;
  }
  result.valid = true;
  result.low_band_ratio = static_cast<float>(low_energy_ / total_energy);
  result.mid_band_ratio = static_cast<float>(mid_energy_ / total_energy);
  result.high_band_ratio = static_cast<float>(high_energy_ / total_energy);
  result.spectral_centroid_hz = centroid_energy_ > kEpsilon
      ? static_cast<float>(centroid_weighted_ / centroid_energy_) : NAN;
  result.spectral_flatness = static_cast<float>(
      flatness_sum_ / std::max<uint16_t>(1, spectral_frames_));
  result.spectral_flux = static_cast<float>(
      flux_sum_ / std::max<int>(1, spectral_frames_ - 1));
  result.crest_factor = rms > kEpsilon ? peak / rms : NAN;
  result.syllabic_modulation = envelopeBandRatio(
      envelope_, envelope_index_, 3.0F, 8.0F);
  breathingPeriodicity(
      envelope_, envelope_index_,
      &result.breathing_periodicity,
      &result.breathing_period_s);

  if (laeq_dba < 35.0F) {
    result.label = "quiet";
    result.confidence = clamp01((40.0F - laeq_dba) / 10.0F);
  } else if (result.crest_factor >= 12.0F && result.spectral_flux >= 0.12F) {
    result.label = "impact_like";
    result.confidence = clamp01(
        0.55F + (result.crest_factor - 12.0F) / 30.0F);
    result.event_detected = true;
  } else if (result.breathing_periodicity >= 0.45F &&
             result.low_band_ratio >= 0.35F &&
             result.spectral_centroid_hz < 700.0F &&
             result.syllabic_modulation < 0.22F) {
    result.label = "snore_like";
    result.confidence = clamp01(
        0.35F * result.breathing_periodicity +
        0.35F * result.low_band_ratio + 0.30F);
    result.event_detected = true;
  } else if (result.syllabic_modulation >= 0.18F &&
             result.mid_band_ratio >= 0.35F &&
             result.spectral_centroid_hz >= 300.0F &&
             result.spectral_centroid_hz <= 3000.0F) {
    result.label = "speech_like";
    result.confidence = clamp01(
        0.40F * result.syllabic_modulation +
        0.35F * result.mid_band_ratio + 0.25F);
    result.event_detected = true;
  } else if (result.spectral_flux < 0.10F &&
             result.syllabic_modulation < 0.15F &&
             result.breathing_periodicity < 0.35F) {
    result.label = "steady_equipment_like";
    result.confidence = clamp01(0.65F - result.spectral_flux);
  } else {
    result.label = "unknown";
    result.confidence = 0.0F;
  }
  return result;
}

}  // namespace zeep
