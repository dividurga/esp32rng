idf_component_register(
    SRCS "rng_analysis_main.c"
    INCLUDE_DIRS ""
    REQUIRES nvs_flash esp_wifi esp_netif esp_event bt bootloader_support esp_rom
)
