// Generated from the stubs: calls that only configure, or that talk to a network the run does not have. They succeed at nothing and return zero;
// what a person would see or hear has its own model in libs.inc.

u8g2_t * U8G2::getU8g2(void) { return nullptr; }
u8x8_t * U8G2::getU8x8(void) { return nullptr; }
uint32_t U8G2::getBusClock(void) { return uint32_t(); }
void U8G2::setBusClock(uint32_t clock_speed) {}
void U8G2::enableUTF8Print(void) {}
void U8G2::disableUTF8Print(void) {}
uint8_t U8G2::getCols(void) { return uint8_t(); }
uint8_t U8G2::getRows(void) { return uint8_t(); }
void U8G2::drawTile(uint8_t x, uint8_t y, uint8_t cnt, uint8_t *tile_ptr) {}
void U8G2::initDisplay(void) {}
void U8G2::setFlipMode(uint8_t mode) {}
void U8G2::setContrast(uint8_t value) {}
void U8G2::setDisplayRotation(const u8g2_cb_t *u8g2_cb) {}
void U8G2::setMaxClipWindow(void) {}
void U8G2::setClipWindow(u8g2_uint_t clip_x0, u8g2_uint_t clip_y0, u8g2_uint_t clip_x1, u8g2_uint_t clip_y1) {}
uint8_t * U8G2::getBufferPtr(void) { return nullptr; }
uint8_t U8G2::getBufferTileHeight(void) { return uint8_t(); }
uint8_t U8G2::getBufferTileWidth(void) { return uint8_t(); }
void U8G2::setAutoPageClear(uint8_t mode) {}
void U8G2::updateDisplayArea(uint8_t tx, uint8_t ty, uint8_t tw, uint8_t th) {}
void U8G2::refreshDisplay(void) {}
void U8G2::setDrawColor(uint8_t color_index) {}
uint8_t U8G2::getDrawColor(void) { return uint8_t(); }
void U8G2::drawPixel(u8g2_uint_t x, u8g2_uint_t y) {}
void U8G2::drawHLine(u8g2_uint_t x, u8g2_uint_t y, u8g2_uint_t w) {}
void U8G2::drawVLine(u8g2_uint_t x, u8g2_uint_t y, u8g2_uint_t h) {}
void U8G2::drawHVLine(u8g2_uint_t x, u8g2_uint_t y, u8g2_uint_t len, uint8_t dir) {}
void U8G2::drawFrame(u8g2_uint_t x, u8g2_uint_t y, u8g2_uint_t w, u8g2_uint_t h) {}
void U8G2::drawRFrame(u8g2_uint_t x, u8g2_uint_t y, u8g2_uint_t w, u8g2_uint_t h, u8g2_uint_t r) {}
void U8G2::drawBox(u8g2_uint_t x, u8g2_uint_t y, u8g2_uint_t w, u8g2_uint_t h) {}
void U8G2::drawRBox(u8g2_uint_t x, u8g2_uint_t y, u8g2_uint_t w, u8g2_uint_t h, u8g2_uint_t r) {}
void U8G2::drawButtonUTF8(u8g2_uint_t x, u8g2_uint_t y, u8g2_uint_t flags, u8g2_uint_t width, u8g2_uint_t padding_h, u8g2_uint_t padding_v, const char *text) {}
void U8G2::drawCircle(u8g2_uint_t x0, u8g2_uint_t y0, u8g2_uint_t rad, uint8_t opt) {}
void U8G2::drawDisc(u8g2_uint_t x0, u8g2_uint_t y0, u8g2_uint_t rad, uint8_t opt) {}
void U8G2::drawEllipse(u8g2_uint_t x0, u8g2_uint_t y0, u8g2_uint_t rx, u8g2_uint_t ry, uint8_t opt) {}
void U8G2::drawFilledEllipse(u8g2_uint_t x0, u8g2_uint_t y0, u8g2_uint_t rx, u8g2_uint_t ry, uint8_t opt) {}
void U8G2::drawLine(u8g2_uint_t x1, u8g2_uint_t y1, u8g2_uint_t x2, u8g2_uint_t y2) {}
void U8G2::setBitmapMode(uint8_t is_transparent) {}
void U8G2::drawBitmap(u8g2_uint_t x, u8g2_uint_t y, u8g2_uint_t cnt, u8g2_uint_t h, const uint8_t *bitmap) {}
void U8G2::drawXBM(u8g2_uint_t x, u8g2_uint_t y, u8g2_uint_t w, u8g2_uint_t h, const uint8_t *bitmap) {}
void U8G2::drawXBMP(u8g2_uint_t x, u8g2_uint_t y, u8g2_uint_t w, u8g2_uint_t h, const uint8_t *bitmap) {}
void U8G2::drawTriangle(int16_t x0, int16_t y0, int16_t x1, int16_t y1, int16_t x2, int16_t y2) {}
void U8G2::setFont(const uint8_t *font) {}
void U8G2::setFontMode(uint8_t is_transparent) {}
void U8G2::setFontDirection(uint8_t dir) {}
int8_t U8G2::getAscent(void) { return int8_t(); }
int8_t U8G2::getDescent(void) { return int8_t(); }
void U8G2::setFontPosBaseline(void) {}
void U8G2::setFontPosBottom(void) {}
void U8G2::setFontPosTop(void) {}
void U8G2::setFontPosCenter(void) {}
void U8G2::setFontRefHeightText(void) {}
void U8G2::setFontRefHeightExtendedText(void) {}
void U8G2::setFontRefHeightAll(void) {}
u8g2_uint_t U8G2::drawGlyphX2(u8g2_uint_t x, u8g2_uint_t y, uint16_t encoding) { return u8g2_uint_t(); }
u8g2_uint_t U8G2::getCursorX(void) { return u8g2_uint_t(); }
u8g2_uint_t U8G2::getCursorY(void) { return u8g2_uint_t(); }
void U8G2::sleepOn(void) {}
void U8G2::sleepOff(void) {}
void U8G2::noDisplay(void) {}
void U8G2::display(void) {}
void U8G2::home(void) {}
uint8_t U8G2::userInterfaceSelectionList(const char *title, uint8_t start_pos, const char *sl) { return uint8_t(); }
uint8_t U8G2::userInterfaceMessage(const char *title1, const char *title2, const char *title3, const char *buttons) { return uint8_t(); }
uint8_t U8G2::userInterfaceInputValue(const char *title, const char *pre, uint8_t *value, uint8_t lo, uint8_t hi, uint8_t digits, const char *post) { return uint8_t(); }
uint8_t U8G2::getMenuEvent(void) { return uint8_t(); }
u8x8_t * U8X8::getU8x8(void) { return nullptr; }
uint32_t U8X8::getBusClock(void) { return uint32_t(); }
void U8X8::setBusClock(uint32_t clock_speed) {}
uint8_t U8X8::getCols(void) { return uint8_t(); }
uint8_t U8X8::getRows(void) { return uint8_t(); }
void U8X8::drawTile(uint8_t x, uint8_t y, uint8_t cnt, uint8_t *tile_ptr) {}
void U8X8::initDisplay(void) {}
void U8X8::sendF(const char *fmt, ...) {}
void U8X8::fillDisplay(void) {}
void U8X8::setFlipMode(uint8_t mode) {}
void U8X8::setContrast(uint8_t value) {}
void U8X8::refreshDisplay(void) {}
void U8X8::setFont(const uint8_t *font_8x8) {}
void U8X8::drawGlyph(uint8_t x, uint8_t y, uint8_t encoding) {}
void U8X8::draw2x2Glyph(uint8_t x, uint8_t y, uint8_t encoding) {}
uint8_t U8X8::getUTF8Len(const char *s) { return uint8_t(); }
void U8X8::setInverseFont(uint8_t value) {}
void U8X8::inverse(void) {}
void U8X8::noInverse(void) {}
void U8X8::enableUTF8Print(void) {}
void U8X8::disableUTF8Print(void) {}
void U8X8::home(void) {}
void U8X8::noDisplay(void) {}
void U8X8::display(void) {}
void LiquidCrystal_I2C::noBlink() {}
void LiquidCrystal_I2C::blink() {}
void LiquidCrystal_I2C::noCursor() {}
void LiquidCrystal_I2C::cursor() {}
void LiquidCrystal_I2C::scrollDisplayLeft() {}
void LiquidCrystal_I2C::scrollDisplayRight() {}
void LiquidCrystal_I2C::leftToRight() {}
void LiquidCrystal_I2C::rightToLeft() {}
bool LiquidCrystal_I2C::getBacklight() { return bool(); }
void LiquidCrystal_I2C::setBacklight(uint8_t new_val) {}
void LiquidCrystal_I2C::autoscroll() {}
void LiquidCrystal_I2C::noAutoscroll() {}
void LiquidCrystal_I2C::createChar(uint8_t, uint8_t[]) {}
void LiquidCrystal_I2C::createChar(uint8_t location, const char *charmap) {}
void LiquidCrystal_I2C::command(uint8_t) {}
void LiquidCrystal_I2C::printstr(const char[]) {}
void CFastLED::setMaxPowerInVoltsAndMilliamps(uint8_t volts, uint32_t milliamps) {}
void CFastLED::setMaxPowerInMilliWatts(uint32_t milliwatts) {}
void CFastLED::setTemperature(const CRGB &temp) {}
void CFastLED::setCorrection(const CRGB &correction) {}
void CFastLED::setDither(uint8_t ditherMode) {}
void CFastLED::setMaxRefreshRate(uint16_t refresh, bool constrain) {}
uint16_t CFastLED::getFPS() { return uint16_t(); }
void CLEDController::showLeds(uint8_t brightness) {}
void CLEDController::clearLeds(int nLeds) {}
SPIClass::SPIClass(uint8_t spi_bus) {}
SPIClass::~SPIClass() {}
bool SPIClass::begin(int8_t sck, int8_t miso, int8_t mosi, int8_t ss) { return bool(); }
void SPIClass::end() {}
void SPIClass::setHwCs(bool use) {}
void SPIClass::setSSInvert(bool invert) {}
void SPIClass::setBitOrder(uint8_t bitOrder) {}
void SPIClass::setDataMode(uint8_t dataMode) {}
void SPIClass::setFrequency(uint32_t freq) {}
void SPIClass::setClockDivider(uint32_t clockDiv) {}
uint32_t SPIClass::getClockDivider() { return uint32_t(); }
void SPIClass::beginTransaction(SPISettings settings) {}
void SPIClass::endTransaction(void) {}
void SPIClass::transfer(void *data, uint32_t size) {}
uint8_t SPIClass::transfer(uint8_t data) { return uint8_t(); }
uint16_t SPIClass::transfer16(uint16_t data) { return uint16_t(); }
uint32_t SPIClass::transfer32(uint32_t data) { return uint32_t(); }
void SPIClass::transferBytes(const uint8_t *data, uint8_t *out, uint32_t size) {}
void SPIClass::transferBits(uint32_t data, uint32_t *out, uint8_t bits) {}
void SPIClass::write(uint8_t data) {}
void SPIClass::write16(uint16_t data) {}
void SPIClass::write32(uint32_t data) {}
void SPIClass::writeBytes(const uint8_t *data, uint32_t size) {}
void SPIClass::writePixels(const void *data, uint32_t size) {}
void SPIClass::writePattern(const uint8_t *data, uint8_t size, uint32_t repeat) {}
int8_t SPIClass::pinSS() { return int8_t(); }
SPISettings::SPISettings() {}
SPISettings::SPISettings(uint32_t clock, uint8_t bitOrder, uint8_t dataMode) {}
HTTPClient::HTTPClient() {}
HTTPClient::~HTTPClient() {}
bool HTTPClient::begin(WiFiClient &client, String url) { return bool(); }
bool HTTPClient::begin(WiFiClient &client, String host, uint16_t port, String uri, bool https) { return bool(); }
bool HTTPClient::begin(String url) { return bool(); }
bool HTTPClient::begin(String url, const char *CAcert) { return bool(); }
bool HTTPClient::begin(String host, uint16_t port, String uri) { return bool(); }
bool HTTPClient::begin(String host, uint16_t port, String uri, const char *CAcert) { return bool(); }
void HTTPClient::end(void) {}
bool HTTPClient::connected(void) { return bool(); }
void HTTPClient::setReuse(bool reuse) {}
void HTTPClient::setUserAgent(const String &userAgent) {}
void HTTPClient::setAuthorization(const char *user, const char *password) {}
void HTTPClient::setAuthorization(const char *auth) {}
void HTTPClient::setAuthorizationType(const char *authType) {}
void HTTPClient::setConnectTimeout(int32_t connectTimeout) {}
void HTTPClient::setTimeout(uint16_t timeout) {}
void HTTPClient::setFollowRedirects(followRedirects_t follow) {}
void HTTPClient::setRedirectLimit(uint16_t limit) {}
bool HTTPClient::setURL(const String &url) { return bool(); }
void HTTPClient::useHTTP10(bool usehttp10) {}
void HTTPClient::addHeader(const String &name, const String &value, bool first, bool replace) {}
int HTTPClient::GET() { return int(); }
int HTTPClient::PATCH(uint8_t *payload, size_t size) { return int(); }
int HTTPClient::PATCH(String payload) { return int(); }
int HTTPClient::POST(uint8_t *payload, size_t size) { return int(); }
int HTTPClient::POST(String payload) { return int(); }
int HTTPClient::PUT(uint8_t *payload, size_t size) { return int(); }
int HTTPClient::PUT(String payload) { return int(); }
int HTTPClient::sendRequest(const char *type, String payload) { return int(); }
int HTTPClient::sendRequest(const char *type, uint8_t *payload, size_t size) { return int(); }
int HTTPClient::sendRequest(const char *type, Stream *stream, size_t size) { return int(); }
void HTTPClient::collectHeaders(const char *headerKeys[], const size_t headerKeysCount) {}
String HTTPClient::header(const char *name) { return String(); }
String HTTPClient::header(size_t i) { return String(); }
String HTTPClient::headerName(size_t i) { return String(); }
int HTTPClient::headers() { return int(); }
bool HTTPClient::hasHeader(const char *name) { return bool(); }
int HTTPClient::getSize(void) { return int(); }
WiFiClient * HTTPClient::getStreamPtr(void) { return nullptr; }
int HTTPClient::writeToStream(Stream *stream) { return int(); }
String HTTPClient::getString(void) { return String(); }
PubSubClient::PubSubClient() {}
PubSubClient::PubSubClient(Client &client) {}
PubSubClient::PubSubClient(IPAddress, uint16_t, Client &client) {}
PubSubClient::PubSubClient(IPAddress, uint16_t, MQTT_CALLBACK_SIGNATURE, Client &client) {}
PubSubClient::PubSubClient(uint8_t *, uint16_t, Client &client) {}
PubSubClient::PubSubClient(const char *, uint16_t, Client &client) {}
PubSubClient::PubSubClient(const char *, uint16_t, MQTT_CALLBACK_SIGNATURE, Client &client) {}
PubSubClient::~PubSubClient() {}
bool PubSubClient::setBufferSize(uint16_t size) { return bool(); }
uint16_t PubSubClient::getBufferSize() { return uint16_t(); }
bool PubSubClient::connect(const char *id) { return bool(); }
bool PubSubClient::connect(const char *id, const char *user, const char *pass) { return bool(); }
bool PubSubClient::connect(const char *id, const char *willTopic, uint8_t willQos, bool willRetain, const char *willMessage) { return bool(); }
bool PubSubClient::connect(const char *id, const char *user, const char *pass, const char *willTopic, uint8_t willQos, bool willRetain, const char *willMessage) { return bool(); }
bool PubSubClient::connect(const char *id, const char *user, const char *pass, const char *willTopic, uint8_t willQos, bool willRetain, const char *willMessage, bool cleanSession) { return bool(); }
void PubSubClient::disconnect() {}
bool PubSubClient::publish(const char *topic, const char *payload) { return bool(); }
bool PubSubClient::publish(const char *topic, const char *payload, bool retained) { return bool(); }
bool PubSubClient::publish(const char *topic, const uint8_t *payload, unsigned int plength) { return bool(); }
bool PubSubClient::publish(const char *topic, const uint8_t *payload, unsigned int plength, bool retained) { return bool(); }
bool PubSubClient::publish_P(const char *topic, const char *payload, bool retained) { return bool(); }
bool PubSubClient::publish_P(const char *topic, const uint8_t *payload, unsigned int plength, bool retained) { return bool(); }
bool PubSubClient::beginPublish(const char *topic, unsigned int plength, bool retained) { return bool(); }
int PubSubClient::endPublish() { return int(); }
size_t PubSubClient::write(uint8_t) { return size_t(); }
size_t PubSubClient::write(const uint8_t *buffer, size_t size) { return size_t(); }
bool PubSubClient::subscribe(const char *topic) { return bool(); }
bool PubSubClient::subscribe(const char *topic, uint8_t qos) { return bool(); }
bool PubSubClient::unsubscribe(const char *topic) { return bool(); }
bool PubSubClient::loop() { return bool(); }
bool PubSubClient::connected() { return bool(); }
int PubSubClient::state() { return int(); }
MDNSResponder::MDNSResponder() {}
MDNSResponder::~MDNSResponder() {}
bool MDNSResponder::begin(const char *hostName) { return bool(); }
void MDNSResponder::end() {}
void MDNSResponder::setInstanceName(String name) {}
void MDNSResponder::setInstanceName(const char *name) {}
bool MDNSResponder::addService(const char *service, const char *proto, uint16_t port) { return bool(); }
bool MDNSResponder::addService(String service, String proto, uint16_t port) { return bool(); }
bool MDNSResponder::addServiceTxt(const char *name, const char *proto, const char *key, const char *value) { return bool(); }
void MDNSResponder::enableArduino(uint16_t port, bool auth) {}
void MDNSResponder::disableArduino() {}
void MDNSResponder::enableWorkstation(int interface) {}
IPAddress MDNSResponder::queryHost(char *host, uint32_t timeout) { return IPAddress(); }
int MDNSResponder::queryService(char *service, char *proto) { return int(); }
int MDNSResponder::queryService(const String &service, const String &proto) { return int(); }
ESP32PWM::ESP32PWM() {}
ESP32PWM::~ESP32PWM() {}
void ESP32PWM::detachPin(int pin) {}
void ESP32PWM::attachPin(uint8_t pin, double freq, uint8_t resolution_bits) {}
void ESP32PWM::write(uint32_t duty) {}
void ESP32PWM::writeScaled(double duty) {}
double ESP32PWM::writeTone(double freq) { return double(); }
double ESP32PWM::setup(double freq, uint8_t resolution_bits) { return double(); }
bool ESP32PWM::attached() { return bool(); }
