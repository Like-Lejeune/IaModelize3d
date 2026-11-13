// What library stubs with inline bodies call in the simulator (firmware_sim/libs.inc); never linked by the compile-only check.
#pragma once
float fw_env_value(int channel);
void fw_said(const char *what);
void fw_wait(long us);
bool fw_has_i2c(int addr);
