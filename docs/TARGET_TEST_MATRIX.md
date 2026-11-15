# Verification of the SPHEREx challenge fields

The example assets are calibrated DR1 and QR3 Level 2 cutouts registered to common ICRS TAN grids. The date count is the November 14 geometric archive audit. The playback count is the number of bundled independent visits. The quality column reports common valid pixels after local wavelength matching for the best bundled pair. Quantitative analysis requires at least 60% common coverage and additional relative registration and effective PSF validation.

| Example and resolver | Input/field center (ICRS degrees) | Reference epoch and reference ICRS position | Width | Archive dates / bundled visits | Baseline | Best pair overlap | Outcome |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| Barnard’s Star · HIP 87937 | 269.45000000, +4.76800000 | J2000.0 · 269.452076959, +4.693364967 · field centered for J2026.0 using catalog proper motion | 3′ | 39 / 3 | 366.99 d | 79.7% | Playback and visual difference pass. The core is partly masked by saturation and the relative astrometry gate found zero usable stable references. Motion remains unconfirmed. |
| Epsilon Indi B · 2MASS J22041052−5646577 | 331.09656943, −56.80083957 | 1999.855 · 331.043833333, −56.782694444 · J2026.0 field center | 3′ | 60 / 3 | 191.97 d | 57.6% | Playback passes. Detector masks and common overlap block pixel comparisons on the bundled pairs. Ba/Bb are unresolved at SPHEREx sampling and combined-source motion remains unmeasured. |
| WISE 0855 · WISE J085510.83−071442.5 | 133.75977000, −7.24218000 | MJD 55320.4 · 133.795224, −7.245138 · J2026.0 field center propagated with proper motion | 5′ | 27 / 2 | 163.46 d | 76.0% | Matched D6 playback and visual difference pass. This verification did not establish a detection of the faint target. |
| WISE 0855 · literal NASA seed | `08h55m10.831s`, `−07d14m42.53s` → 133.79512917, −7.24514722 | Historical WISE position quoted by NASA. The wider field includes the observation-era center ∼2.1′ west. | 6′ | 27 / 2 | 163.46 d | 65.1% | Literal field playback and visual difference pass. Two matched references fall below the ranking gate. |
| RW Aurigae · RW Aur | 76.95654167, +30.40144444 | J2000 · 76.95654167, +30.40144444 | 3′ | 35 / 3 | 370.91 d | 82.4% | Matched near-infrared playback and visual difference pass. Blended light and saturation-related masks make a quantitative brightness claim unreliable. |
| R Draconis · R Dra | 248.16761000, +66.75498000 | J2000 · 248.16760750, +66.754984167 | 3′ | 78 / 3 | 399.97 d | 79.3% | Matched near-infrared playback and visual difference pass. The central signal is affected by saturation-related flags, and the relative match lacks stable references. |

The forecast fit correctly returns measurements and an unavailable status for these real selections until an unambiguous source has at least three independently validated positions. The controlled track fixture checks an extrapolation against a withheld epoch. [Comparison and tracking specification](COMPARISON_AND_TRACKING.md)

## Bundled observations

Wavelengths are the actual calibrated band center at each preset's center. The archive URLs, bandwidths, observation end times, mask names, product IDs, reference coordinates and version are in the corresponding manifest. Run `python -m tools.verify_presets` to verify every content hash, analysis array, variance, WCS-oriented mask, sample selection and baseline.

| Example | Release | Observation ID | Start UTC | Detector | Center µm | Valid pixels |
| --- | --- | --- | --- | ---: | ---: | ---: |
| Barnard’s Star | DR1 | `2025W33_2C_0321_1` | 2025-08-15 20:45:11.337 | 6 | 4.928207 | 83.5% |
| Barnard’s Star | DR1 | `2026W12_2A_0520_4` | 2026-03-22 08:50:47.183 | 6 | 4.929935 | 94.8% |
| Barnard’s Star | QR3 | `2026W34_1A_0176_2` | 2026-08-17 20:25:21.494 | 6 | 4.941452 | 91.3% |
| Epsilon Indi B | DR1 | `2025W41_2B_0301_1` | 2025-10-10 20:22:54.824 | 4 | 2.498113 | 51.8% |
| Epsilon Indi B | DR1 | `2025W42_2A_0059_1` | 2025-10-16 18:05:52.565 | 4 | 2.497889 | 71.5% |
| Epsilon Indi B | DR1 | `2026W17_1B_0162_4` | 2026-04-20 19:39:28.357 | 4 | 2.522017 | 91.4% |
| WISE 0855 | DR1 | `2025W46_1A_0076_3` | 2025-11-10 07:14:12.445 | 6 | 4.513411 | 91.3% |
| WISE 0855 | DR1 | `2026W17_1B_0507_1` | 2026-04-22 18:10:31.030 | 6 | 4.518386 | 87.5% |
| WISE 0855 · NASA seed | DR1 | `2025W46_1A_0076_3` | 2025-11-10 07:14:12.445 | 6 | 4.511513 | 91.3% |
| WISE 0855 · NASA seed | DR1 | `2026W17_1B_0507_1` | 2026-04-22 18:10:31.030 | 6 | 4.520420 | 89.8% |
| RW Aurigae | DR1 | `2025W36_1A_0663_1` | 2025-09-03 23:53:31.971 | 1 | 0.972122 | 92.2% |
| RW Aurigae | DR1 | `2026W10_2B_0137_2` | 2026-03-06 05:33:03.427 | 1 | 0.964814 | 93.3% |
| RW Aurigae | QR3 | `2026W37_1A_0524_1` | 2026-09-09 21:42:13.876 | 1 | 0.973875 | 74.9% |
| R Draconis | DR1 | `2025W23_2B_0206_1` | 2025-06-06 11:22:23.875 | 1 | 0.943250 | 76.9% |
| R Draconis | DR1 | `2025W42_2A_0526_2` | 2025-10-19 00:57:25.434 | 1 | 0.941265 | 83.4% |
| R Draconis | QR3 | `2026W28_2A_0376_3` | 2026-07-11 10:39:46.294 | 1 | 0.940818 | 85.3% |

The catalog links are stored beside each preset center. The brown dwarf Epsilon Indi B is separate from ε Indi A. The motion-corrected centers are field centers derived from catalog astrometry. None is presented as a measured centroid from these exposures. [Archive availability and count reproduction](OBSERVATION_AVAILABILITY.md) · [DR1 DOI](https://doi.org/10.26131/IRSA678) · [QR3 DOI](https://doi.org/10.26131/IRSA662)
