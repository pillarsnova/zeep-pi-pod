#include "audio_meter.h"

#include <Preferences.h>

#include <algorithm>
#include <cmath>

#include "board_config.h"

namespace zeep {

namespace {

constexpr uint32_t kSampleRateHz = 48000;
constexpr uint32_t kWindowSamples = kSampleRateHz * 10;
constexpr size_t kReadSamples = 1024;
constexpr float kFullScale24 = 8388607.0F;
constexpr float kReferenceSplDb = 94.0F;
constexpr float kSensitivityDbfs = -26.0F;
constexpr float kSineRmsCorrectionDb = 3.0102999566F;
constexpr float kClipThreshold = 0.98F;
constexpr float kMaxClipRatio = 0.001F;
constexpr float kMaxZeroRatio = 0.99F;

Preferences preferences;

struct BiquadCoefficients {
  double b0;
  double b1;
  double b2;
  double a1;
  double a2;
};

class Biquad {
 public:
  explicit Biquad(BiquadCoefficients coefficients)
      : coefficients_(coefficients) {}

  double process(double input) {
    const double output = coefficients_.b0 * input + delay_1_;
    delay_1_ = coefficients_.b1 * input -
               coefficients_.a1 * output + delay_2_;
    delay_2_ = coefficients_.b2 * input -
               coefficients_.a2 * output;
    return output;
  }

 private:
  BiquadCoefficients coefficients_;
  double delay_1_ = 0.0;
  double delay_2_ = 0.0;
};

// A-weighting at 48 kHz. Coefficients are generated from the IEC analogue
// pole/zero definition with a bilinear transform and normalized at 1 kHz.
// The host regression test independently verifies the frequency response.
Biquad a_weighting_1({
    0.23418304260355596,
    -0.46836608520711193,
    0.23418304260355596,
    -1.9946144559930215,
    0.99462170701408426,
});
Biquad a_weighting_2({
    1.0,
    -2.0,
    1.0,
    -1.8938704947230707,
    0.89515976909466166,
});
Biquad a_weighting_3({
    1.0,
    2.0,
    1.0,
    -0.22455845805977914,
    0.012606625271546396,
});

double dc_previous_input = 0.0;
double dc_previous_output = 0.0;
double sum_square_unweighted = 0.0;
double sum_square_a_weighted = 0.0;
float peak_normalized = 0.0F;
uint32_t accumulated_samples = 0;
uint32_t clipped_samples = 0;
uint32_t zero_samples = 0;
uint32_t read_errors = 0;
uint32_t window_started_ms = 0;

double dcBlock(double input) {
  constexpr double kPole = 0.9992;
  const double output = input - dc_previous_input +
                        kPole * dc_previous_output;
  dc_previous_input = input;
  dc_previous_output = output;
  return output;
}

float dbfsFromRms(double rms) {
  if (!std::isfinite(rms) || rms <= 0.0) {
    return NAN;
  }
  return static_cast<float>(20.0 * std::log10(rms));
}

}  // namespace

bool AudioMeter::begin() {
  preferences.begin("zeep-sound", false);
  calibration_offset_db_ = preferences.getFloat("offset-db", 0.0F);
  if (!isfinite(calibration_offset_db_) ||
      calibration_offset_db_ < -30.0F ||
      calibration_offset_db_ > 30.0F) {
    calibration_offset_db_ = 0.0F;
  }

  i2s_config_t i2s_config = {};
  i2s_config.mode = static_cast<i2s_mode_t>(I2S_MODE_MASTER | I2S_MODE_RX);
  i2s_config.sample_rate = kSampleRateHz;
  i2s_config.bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT;
  i2s_config.channel_format = I2S_CHANNEL_FMT_ONLY_LEFT;
  i2s_config.communication_format = I2S_COMM_FORMAT_STAND_I2S;
  i2s_config.intr_alloc_flags = ESP_INTR_FLAG_LEVEL1;
  i2s_config.dma_buf_count = 8;
  i2s_config.dma_buf_len = 512;
  i2s_config.use_apll = true;
  i2s_config.tx_desc_auto_clear = false;
  i2s_config.fixed_mclk = 0;
  if (i2s_driver_install(I2S_NUM_0, &i2s_config, 0, nullptr) != ESP_OK) {
    return false;
  }

  i2s_pin_config_t pin_config = {};
  pin_config.mck_io_num = I2S_PIN_NO_CHANGE;
  pin_config.bck_io_num = board::kMicBclk;
  pin_config.ws_io_num = board::kMicWordSelect;
  pin_config.data_out_num = I2S_PIN_NO_CHANGE;
  pin_config.data_in_num = board::kMicData;
  if (i2s_set_pin(I2S_NUM_0, &pin_config) != ESP_OK) {
    i2s_driver_uninstall(I2S_NUM_0);
    return false;
  }

  healthy_ = xTaskCreatePinnedToCore(
      taskEntry,
      "sph0645-laeq",
      8192,
      this,
      4,
      &task_handle_,
      0) == pdPASS;
  return healthy_;
}

bool AudioMeter::takeWindow(SoundWindow* output) {
  if (output == nullptr) {
    return false;
  }
  portENTER_CRITICAL(&result_lock_);
  if (!pending_.ready) {
    portEXIT_CRITICAL(&result_lock_);
    return false;
  }
  *output = pending_;
  pending_.ready = false;
  portEXIT_CRITICAL(&result_lock_);
  return true;
}

bool AudioMeter::setCalibrationOffset(float offset_db) {
  if (!isfinite(offset_db) || offset_db < -30.0F || offset_db > 30.0F) {
    return false;
  }
  if (preferences.putFloat("offset-db", offset_db) != sizeof(float)) {
    return false;
  }
  portENTER_CRITICAL(&result_lock_);
  calibration_offset_db_ = offset_db;
  portEXIT_CRITICAL(&result_lock_);
  return true;
}

float AudioMeter::calibrationOffset() const {
  portENTER_CRITICAL(&result_lock_);
  const float value = calibration_offset_db_;
  portEXIT_CRITICAL(&result_lock_);
  return value;
}

bool AudioMeter::healthy() const {
  return healthy_;
}

void AudioMeter::taskEntry(void* context) {
  static_cast<AudioMeter*>(context)->readTask();
}

void AudioMeter::readTask() {
  int32_t samples[kReadSamples];
  while (true) {
    size_t bytes_read = 0;
    const esp_err_t result = i2s_read(
        I2S_NUM_0,
        samples,
        sizeof(samples),
        &bytes_read,
        pdMS_TO_TICKS(250));
    if (result != ESP_OK || bytes_read == 0) {
      ++read_errors;
      continue;
    }

    const size_t sample_count = bytes_read / sizeof(int32_t);
    for (size_t index = 0; index < sample_count; ++index) {
      if (accumulated_samples == 0) {
        window_started_ms = millis();
      }
      // ESP-IDF Philips standard format resolves the one-bit I2S delay. The
      // SPH0645 24-bit word is MSB-aligned in the 32-bit DMA slot.
      const int32_t sample_24 = samples[index] >> 8;
      const double normalized = static_cast<double>(sample_24) / kFullScale24;
      const double unweighted = dcBlock(normalized);
      double weighted = a_weighting_1.process(unweighted);
      weighted = a_weighting_2.process(weighted);
      weighted = a_weighting_3.process(weighted);

      sum_square_unweighted += unweighted * unweighted;
      sum_square_a_weighted += weighted * weighted;
      peak_normalized = std::max(
          peak_normalized,
          static_cast<float>(std::abs(normalized)));
      if (std::abs(normalized) >= kClipThreshold) {
        ++clipped_samples;
      }
      if (sample_24 == 0) {
        ++zero_samples;
      }
      ++accumulated_samples;

      if (accumulated_samples >= kWindowSamples) {
        publishAccumulator();
      }
    }
  }
}

void AudioMeter::publishAccumulator() {
  SoundWindow window;
  window.ready = true;
  window.sample_count = accumulated_samples;
  window.window_ms = static_cast<uint32_t>(
      1000ULL * accumulated_samples / kSampleRateHz);
  window.wall_window_ms = millis() - window_started_ms;
  window.clipped_samples = clipped_samples;
  window.zero_samples = zero_samples;
  window.read_errors = read_errors;
  window.peak = peak_normalized;
  window.calibration_offset_db = calibrationOffset();

  const double rms = std::sqrt(
      sum_square_unweighted / accumulated_samples);
  const double a_weighted_rms = std::sqrt(
      sum_square_a_weighted / accumulated_samples);
  window.rms = static_cast<float>(rms);
  window.dbfs = dbfsFromRms(rms);
  window.a_weighted_dbfs = dbfsFromRms(a_weighted_rms);
  window.laeq_dba = kReferenceSplDb - kSensitivityDbfs +
                    kSineRmsCorrectionDb +
                    window.a_weighted_dbfs +
                    window.calibration_offset_db;

  const float clip_ratio = static_cast<float>(clipped_samples) /
                           accumulated_samples;
  const float zero_ratio = static_cast<float>(zero_samples) /
                           accumulated_samples;
  if (!isfinite(window.laeq_dba) || !isfinite(window.dbfs)) {
    window.invalid_reason = "non_finite";
  } else if (read_errors > 0) {
    window.invalid_reason = "i2s_read_error";
  } else if (window.wall_window_ms < 9000 || window.wall_window_ms > 11000) {
    window.invalid_reason = "sample_clock_mismatch";
  } else if (clip_ratio > kMaxClipRatio) {
    window.invalid_reason = "clipping";
  } else if (zero_ratio > kMaxZeroRatio) {
    window.invalid_reason = "digital_silence";
  } else if (window.laeq_dba < 30.0F || window.laeq_dba > 130.0F) {
    window.invalid_reason = "outside_cem_range";
  } else {
    window.valid = true;
  }

  portENTER_CRITICAL(&result_lock_);
  pending_ = window;
  portEXIT_CRITICAL(&result_lock_);

  sum_square_unweighted = 0.0;
  sum_square_a_weighted = 0.0;
  peak_normalized = 0.0F;
  accumulated_samples = 0;
  clipped_samples = 0;
  zero_samples = 0;
  read_errors = 0;
  window_started_ms = 0;
}

}  // namespace zeep
