/*
 * ESP32 Hardware RNG Analysis Firmware
 * ECE580 Hardware Security
 *
 * Collects random samples from the ESP32 hardware RNG under eight entropy
 * source configurations, outputting results over UART for offline analysis.
 *
 * Entropy source modes (CONFIG_RNG_ENTROPY_MODE):
 *   0  BARE        - No extra entropy: RF off, ADC off (weakest)
 *   1  WIFI        - WiFi RF subsystem active, not connected
 *   2  BT          - Bluetooth RF active (BLE mode)
 *   3  WIFI_BT     - WiFi + Bluetooth RF both active
 *   4  ADC         - ADC continuously sampling a floating pin
 *   5  ADC_WIFI    - ADC + WiFi RF
 *   6  ADC_BT      - ADC + Bluetooth RF
 *   7  ADC_WIFI_BT - All entropy sources active (strongest)
 *
 * Per the ESP32 TRM, the hardware RNG register (WDEV_RND_REG) is
 * continuously updated by RF/ADC noise when those peripherals are active.
 * Without them the register is driven only by the internal RC oscillator,
 * producing measurably weaker randomness.
 *
 * Output protocol (over UART, 115200 baud):
 *   === ESP32 RNG ANALYSIS ===
 *   MODE: <name>
 *   MODE_ID: <0-7>
 *   SAMPLES: <n>
 *   BITS_PER_SAMPLE: 32
 *   BEGIN_DATA
 *   XXXXXXXX          <- one 8-char uppercase hex value per line
 *   ...
 *   END_DATA
 *   === COLLECTION COMPLETE ===
 */

#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_system.h"
#include "esp_random.h"
#include "esp_log.h"
#include "esp_rom_sys.h"
#include "nvs_flash.h"
#include "sdkconfig.h"

/* ---- Mode constants ---- */
#define MODE_BARE         0
#define MODE_WIFI         1
#define MODE_BT           2
#define MODE_WIFI_BT      3
#define MODE_ADC          4
#define MODE_ADC_WIFI     5
#define MODE_ADC_BT       6
#define MODE_ADC_WIFI_BT  7

#define MODE_NEEDS_WIFI(m)  ((m)==1||(m)==3||(m)==5||(m)==7)
#define MODE_NEEDS_BT(m)    ((m)==2||(m)==3||(m)==6||(m)==7)
#define MODE_NEEDS_ADC(m)   ((m)==4||(m)==5||(m)==6||(m)==7)

static const char *TAG = "RNG";

static const char *MODE_NAMES[] = {
    "BARE",
    "WIFI",
    "BT",
    "WIFI_BT",
    "ADC",
    "ADC_WIFI",
    "ADC_BT",
    "ADC_WIFI_BT"
};

/* ==================================================================
 * WiFi initialisation — activates the RF subsystem without
 * associating to any network.  The RF noise immediately begins
 * feeding the hardware RNG entropy pool.
 * ================================================================== */
#include "esp_wifi.h"
#include "esp_netif.h"
#include "esp_event.h"

static void entropy_init_wifi(void)
{
    ESP_LOGI(TAG, "Initialising WiFi RF (entropy source, no association)");
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_start());

    vTaskDelay(pdMS_TO_TICKS(500));
    ESP_LOGI(TAG, "WiFi RF active");
}

/* ==================================================================
 * Bluetooth initialisation — enables the BT controller in BLE-only
 * mode so the RF subsystem is active.  Bluedroid stack is brought up
 * to ensure the full entropy path is active.
 * ================================================================== */
#include "esp_bt.h"
#include "esp_bt_main.h"

static void entropy_init_bt(void)
{
    ESP_LOGI(TAG, "Initialising Bluetooth RF (BLE mode, entropy source)");

    esp_bt_controller_config_t bt_cfg = BT_CONTROLLER_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_bt_controller_init(&bt_cfg));
    ESP_ERROR_CHECK(esp_bt_controller_enable(ESP_BT_MODE_BLE));
    ESP_ERROR_CHECK(esp_bluedroid_init());
    ESP_ERROR_CHECK(esp_bluedroid_enable());

    vTaskDelay(pdMS_TO_TICKS(500));
    ESP_LOGI(TAG, "Bluetooth RF active");
}

/* ==================================================================
 * ADC entropy initialisation — enables the internal SAR ADC entropy
 * path via bootloader_random_enable().  This is the only supported way
 * to feed the hardware RNG from the SAR ADC in application code; using
 * the adc_oneshot API does NOT enable the internal entropy path.
 * ================================================================== */
#include "bootloader_random.h"

static void entropy_init_adc(void)
{
    ESP_LOGI(TAG, "Enabling SAR ADC entropy source (bootloader_random_enable)");
    bootloader_random_enable();
    ESP_LOGI(TAG, "SAR ADC entropy source active");
}

/* ==================================================================
 * Sample collection
 * ================================================================== */
static void collect_and_print(int mode, int n_samples)
{
    printf("\r\n=== ESP32 RNG ANALYSIS ===\r\n");
    printf("MODE: %s\r\n",        MODE_NAMES[mode]);
    printf("MODE_ID: %d\r\n",     mode);
    printf("SAMPLES: %d\r\n",     n_samples);
    printf("BITS_PER_SAMPLE: 32\r\n");
    printf("BEGIN_DATA\r\n");
    fflush(stdout);

    for (int i = 0; i < n_samples; i++) {
        /* Busy-wait before each read so the RNG register has been updated
         * since the previous read, regardless of UART TX buffering.
         * 100 µs gives ≥200 HSADC injections (RF modes, 2 MHz) or
         * ≥20 SAR ADC injections (ADC-only mode, ~200 kSPS). */
        esp_rom_delay_us(100);
        printf("%08" PRIX32 "\r\n", esp_random());
    }

    printf("END_DATA\r\n");
    printf("=== COLLECTION COMPLETE ===\r\n");
    fflush(stdout);
}

/* ==================================================================
 * Entry point
 * ================================================================== */
void app_main(void)
{
    const int mode     = CONFIG_RNG_ENTROPY_MODE;
    const int n_samples = CONFIG_RNG_NUM_SAMPLES;

    ESP_LOGI(TAG, "ESP32 RNG Analysis — mode %d (%s), %d samples",
             mode, MODE_NAMES[mode], n_samples);

    /* NVS is required by WiFi and Bluetooth drivers */
    esp_err_t nvs_ret = nvs_flash_init();
    if (nvs_ret == ESP_ERR_NVS_NO_FREE_PAGES ||
        nvs_ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        nvs_ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(nvs_ret);

    /* Release BT memory when BT is not needed, freeing RAM for WiFi */
    if (!MODE_NEEDS_BT(mode)) {
        esp_bt_controller_mem_release(ESP_BT_MODE_BTDM);
    }

    /* Initialise only the entropy sources required for this mode */
    if (MODE_NEEDS_WIFI(mode)) {
        entropy_init_wifi();
    }

    if (MODE_NEEDS_BT(mode)) {
        entropy_init_bt();
    }

    if (MODE_NEEDS_ADC(mode)) {
        entropy_init_adc();
    }

    /* Short stabilisation delay before sampling */
    vTaskDelay(pdMS_TO_TICKS(200));

    collect_and_print(mode, n_samples);

    /* Idle — reset the board to run again */
    while (1) {
        vTaskDelay(pdMS_TO_TICKS(30000));
    }
}
