# Expense for v1

Updated Oct 5, 2026 · Bhavik Fulfagar

v1 hardware for the AI Assistant Glasses costs about ₹2,345–3,480 against a ₹4,000 budget. Every part is off-the-shelf, nothing needs a custom PCB, and v1 runs on USB power from a power bank.

## Parts list

The board and amplifier prices are from Indian store listings in October 2026; everything else is a rough local estimate, so check before buying.

| Part | What to buy | Qty | Approx. price (₹) |
| --- | --- | --- | --- |
| Main board | Seeed XIAO ESP32S3 Sense (camera and mic included) | 1 | 1,700 |
| Amplifier | MAX98357A I2S amplifier module | 1 | 250 |
| Speaker | 8 Ω, 1 W, 20–28 mm round or slim rectangular | 1 | 50–150 |
| Buttons | 6 mm tactile push buttons: Look, Ask and one spare | 3 | 15–30 |
| Heatsink | Small adhesive heatsink, about 10×10 mm | 1 | 30–50 |
| Frame | Safety glasses with wide, flat arms | 1 | 100–200 |
| Wiring kit | 28–30 AWG silicone wire, JST-PH 2.0 connectors (2- and 3-pin), heat-shrink, foam tape, zip ties | 1 set | 200–300 |
| Power | USB-C cable (1–1.5 m) and a power bank; skip if you own them | 1 each | 0–800 |
| **Total for v1** | | | **2,345–3,480** |

Not needed for v1: a protected 3.7 V LiPo, 500–1000 mAh with a JST plug (about ₹250–450), for when the glasses move to battery power.

## Circuit

The camera and mic are already on the Sense board, so only the two buttons, amplifier, speaker and power need wiring.

```text
Power bank ──USB-C──► XIAO ESP32S3 Sense            MAX98357A            Speaker
                      D1 (GPIO2)  ───────────────── BCLK
                      D3 (GPIO4)  ───────────────── LRC
                      D6 (GPIO43) ───────────────── DIN
                      5V          ───────────────── VIN
                      GND         ───────────────── GND
                                                    SPK+ ──────────────── +
                                                    SPK− ──────────────── −

Look button:  leg 1 ── D0 (GPIO1)       leg 2 ── GND
Ask button:   leg 1 ── D7 (GPIO44)      leg 2 ── GND
```

| XIAO pin | Connects to | Purpose |
| --- | --- | --- |
| D0 (GPIO1) | Look button, one leg | Photo + question; the other leg goes to GND, no resistor needed |
| D7 (GPIO44) | Ask button, one leg | Question only; the other leg goes to GND, no resistor needed |
| D1 (GPIO2) | Amp BCLK | I2S bit clock |
| D3 (GPIO4) | Amp LRC | I2S word select |
| D6 (GPIO43) | Amp DIN | I2S audio data |
| 5V | Amp VIN | Amp power from USB, louder than 3.3 V |
| GND | Amp GND and both buttons' other legs | Common ground |
| USB-C port | Power bank | Powers everything in v1 |

The amp's SPK+ and SPK− go to the speaker's + and −. Leave the amp's GAIN and SD pins unconnected: most MAX98357A modules then default to about 9 dB gain and mono output, but check your module's labels.

Pins kept free: D4 and D5 for I2C (a sensor or small display in Phase 2), D8–D10 for the Sense board's microSD slot. D2 stays unused because GPIO3 is a strapping pin.

Wiring tips: keep the three I2S wires under about 10 cm, and put a JST-PH connector on the amp, speaker and both button leads so each part unplugs.

Firmware settings: Arduino framework built with arduino-cli, with OPI PSRAM turned on in the board options. The mic uses I2S0 in PDM mode and the amp uses I2S1, so the two never share an audio peripheral.

## Mounting

All parts go on the right arm of a pair of safety glasses, so only one arm needs wiring.

```text
front                                                        back
[lens]=[XIAO + camera]--[amp]---[Look + Ask]-----[speaker]  (ear)
        at the hinge,               on top,       points into    \
        tilted 10–15° down          under finger  the ear,        USB-C cable, zip-tied
                                                  ~1 cm away      behind the ear
                                                                  → power bank in pocket
```

- **Board and camera:** at the right hinge, facing forward and tilted 10–15° down, because you look down at the bench. Stick the heatsink on the board and keep the board from touching your skin; camera plus Wi-Fi runs warm.
- **Amplifier:** right behind the board along the arm, with short wires to it.
- **Buttons:** Look and Ask side by side on top of the arm, where your index finger rests. Give them different caps, or put a small spacer between them, so you can tell them apart by touch.
- **Speaker:** near the end of the arm, pointing into your ear canal from about 1 cm away.
- **Cable:** down the back of the arm and behind the ear to a power bank in your pocket. Zip-tie it to the frame so a tug pulls on the frame, not on the board's USB port.
- **Attaching:** foam tape and zip ties for v1. Seeed publishes 3D-printable shell files for this board that can be adapted for a cleaner mount later.
- **Power bank:** some banks switch off when the current draw is low. If yours does, use one with a low-current or trickle mode.

## Assembly order

Test each part on the desk before anything goes on the frame; a fault is easy to find on a breadboard and hard to find on your head.

1. Flash a test sketch to the bare board: take a photo and record 5 s of audio, then check both on the laptop.
2. On a breadboard, wire the amplifier and speaker and play a test tone.
3. Add both buttons and confirm Look is read on D0 and Ask on D7, each with its own sound.
4. Run the full loop against the laptop server while everything is still on the breadboard.
5. Solder the final wires with JST connectors and heat-shrink every joint.
6. Mount the parts on the frame, add the heatsink, then route and zip-tie the cable.
7. Run 20 queries in a row while wearing the glasses, as the spec's reliability target asks.

## Built to carry over to Phase 2

Nothing bought for v1 is thrown away later; each choice leaves room for the next version.

- **Connectors, not solder:** JST connectors on the amp, speaker and buttons let every part move to a 3D-printed frame without rewiring.
- **Spare pins:** the I2C pins (D4, D5) and microSD pins (D8–D10) stay free for future sensors, a small display or on-device logging.
- **Battery later:** the XIAO has LiPo charging built in, so moving off USB means soldering a protected cell to its BAT pads. No separate charger board.
- **Same API:** the laptop server's `/query` endpoint stays the same, so swapping Gemini for a local model later is a server-only change.
- **Same firmware base:** the Arduino core sits on ESP-IDF, so lower-level features such as audio streaming or deep sleep can use ESP-IDF calls without starting over.
