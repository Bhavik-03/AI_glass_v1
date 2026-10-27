# M17-T6 results: 34 pairs, then the held-out T5 points

Evidence for the writer guard's thresholds (design.md, Session writer). The 34 pairs are frozen in `tests/fixtures/t6_pairs.json`. The rules were fixed from the 34 alone, then applied once, unchanged, to the held-out T5 points.

Profile values only (slot labels excluded). Rules, decided from these 34 pairs alone: reject as `ungrounded` when the grounded share is 0.00; reject as `known` when the profile covers >= 0.50 of the point's stems or >= 2 stems are in the profile values but not in the user's turns. g = share of the point's content stems in the user's turns; k = share in the profile values; leak = stems in the profile values and not in the user's turns; n = content stems in the point.

| id | grp | g | k | leak | n | expected | guard | result | point |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | A | 0.64 | 0.00 | 0  | 11 | keep | pass | passes | Prototyping wind-turbine blades in 3D printed PLA before moving to carbon fibre |
| 2 | A | 1.00 | 0.00 | 0  | 9 | keep | pass | passes | Project guide Dr Rao wants a progress report every Friday |
| 3 | A | 0.89 | 0.00 | 0  | 9 | keep | pass | passes | Always sketches the free-body diagram before writing any equation |
| 4 | B | 0.43 | 0.00 | 0  | 7 | keep | pass | passes | Studies in the library basement because the hostel is too noisy |
| 5 | B | 0.60 | 0.10 | 0  | 10 | keep | pass | passes | Wants what he builds cheap enough for his father, an autorickshaw driver, to buy |
| 6 | B | 0.25 | 0.00 | 0  | 4 | keep | pass | passes | Has no laptop of their own at present |
| 7 | B | 0.38 | 0.00 | 0  | 8 | keep | pass | passes | Prefers being told which formula applies instead of a full derivation |
| 8 | C | 0.00 | 0.00 | 0  | 5 | reject ungrounded | ungrounded | caught | Runs a drone photography side business |
| 9 | C | 0.00 | 0.00 | 0  | 4 | reject ungrounded | ungrounded | caught | Is a member of the college debate team |
| 10 | C | 0.00 | 0.00 | 0  | 6 | reject ungrounded | ungrounded | caught | Looks after two younger siblings at home |
| 11 | D | 0.20 | 0.00 | 0  | 5 | reject ungrounded | pass | MISSED (unguarded) | Interns at a steel fabrication shop on Saturdays |
| 12 | D | 0.33 | 0.00 | 0  | 6 | reject ungrounded | pass | MISSED (unguarded) | Owns a go-kart track business with a cousin |
| 13 | D | 0.33 | 0.00 | 0  | 6 | reject ungrounded | pass | MISSED (unguarded) | Is writing a research paper on anodising aluminium alloys |
| 14 | E | 0.86 | 0.00 | 0  | 7 | reject ungrounded | pass | MISSED (unguarded) | Leading the chassis team for the college solar car, a team of twelve |
| 15 | E | 0.62 | 0.00 | 0  | 8 | reject ungrounded | pass | MISSED (unguarded) | Switched from FEA to hand calculations for the beam after the licence expired |
| 16 | E | 0.71 | 0.00 | 0  | 7 | reject ungrounded | pass | MISSED (unguarded) | Borrowed an A1 drawing board from his brother for the semester |
| 17 | E | 0.57 | 0.00 | 0  | 7 | reject ungrounded | pass | MISSED (unguarded) | Reading Shigley for machine design, currently on the gears chapter |
| 18 | F | 0.33 | 0.00 | 0  | 3 | keep | pass | passes | Has a long commute to campus |
| 19 | F | 0.25 | 0.00 | 0  | 4 | reject ungrounded | pass | MISSED (unguarded) | Is behind on the standard mathematics sequence |
| 20 | F | 0.29 | 0.00 | 0  | 7 | keep | pass | passes | Plans experiments around a single weekly lab slot |
| 21 | G | 0.67 | 0.83 | 1 mechanical | 6 | reject known | known (share) | caught | Studies mechanical engineering in the second year in Nagpur |
| 22 | G | 0.60 | 0.60 | 2 build,vehicl | 5 | reject known | known (share+leak) | caught | Wants to build electric vehicles eventually |
| 23 | G | 0.80 | 0.80 | 1 pass | 5 | reject known | known (share) | caught | Priority is passing the thermodynamics exam in December |
| 24 | H | 0.67 | 0.17 | 1 time | 6 | keep | pass | passes | Can only work on the project in free time on weekends |
| 25 | H | 0.50 | 0.10 | 1 step | 10 | keep | pass | passes | Follows a fixed three-step routine: clamp the specimen, zero the gauge, load it |
| 26 | H | 0.57 | 0.14 | 1 plain | 7 | keep | pass | passes | Prefers plain black-line diagrams without shading |
| 27 | H | 0.67 | 0.17 | 1 short | 6 | keep | pass | passes | Report summary must be a short two pages |
| 28 | I | 0.62 | 0.38 | 3 engineer,mechanical,student | 8 | reject known | known (leak) | caught | Mechanical engineering student fabricating a hydraulic press for the college fest |
| 29 | I | 0.56 | 0.33 | 3 second,student,year | 9 | reject known | known (leak) | caught | Second-year student running a WhatsApp group to trade past papers |
| 30 | I | 0.75 | 0.25 | 2 nagpur,student | 8 | reject known | known (leak) | caught | Nagpur student earning pocket money by fixing neighbours' bicycles |
| 31 | J | 0.38 | 0.00 | 0  | 8 | reject ungrounded | pass | MISSED (unguarded) | Volunteers on weekends at a charity that repairs plastic water tanks for villages |
| 32 | J | 0.38 | 0.00 | 0  | 8 | reject ungrounded | pass | MISSED (unguarded) | Plans to join a Japanese exchange programme in the department next term |
| 33 | J | 0.38 | 0.12 | 1 student | 8 | reject ungrounded | pass | MISSED (unguarded) | Sells translated engine manuals to other students in the hostel on Sundays |
| 34 | K | 0.89 | 0.33 | 0  | 9 | keep | pass | passes | Solves one thermodynamics past paper every night to prepare for the exam |

## Per group

- **A**: grounded min 0.64, max 1.00; 1 passes; 2 passes; 3 passes
- **B**: grounded min 0.25, max 0.60; 4 passes; 5 passes; 6 passes; 7 passes
- **C**: grounded min 0.00, max 0.00; 8 caught (ungrounded); 9 caught (ungrounded); 10 caught (ungrounded)
- **D**: grounded min 0.20, max 0.33; 11 MISSED (unguarded); 12 MISSED (unguarded); 13 MISSED (unguarded)
- **E**: grounded min 0.57, max 0.86; 14 MISSED (unguarded); 15 MISSED (unguarded); 16 MISSED (unguarded); 17 MISSED (unguarded)
- **F**: grounded min 0.25, max 0.33; 18 passes; 19 MISSED (unguarded); 20 passes
- **G**: grounded min 0.60, max 0.80; 21 caught (known, share); 22 caught (known, share+leak); 23 caught (known, share)
- **H**: grounded min 0.50, max 0.67; 24 passes; 25 passes; 26 passes; 27 passes
- **I**: grounded min 0.56, max 0.75; 28 caught (known, leak); 29 caught (known, leak); 30 caught (known, leak)
- **J**: grounded min 0.38, max 0.38; 31 MISSED (unguarded); 32 MISSED (unguarded); 33 MISSED (unguarded)
- **K**: grounded min 0.89, max 0.89; 34 passes

Legitimate pairs: 14; wrongly rejected: 0. Highest known share among legitimate pairs: 0.33 (pair 34); lowest known share among G: 0.60.

## Held-out T5 points (one pass, rules unchanged)

Profile values: identity 'Final-year electronics engineering student in Pune', goal_long 'Work on embedded machine learning'. Each distinct returned point across both spike runs; `occurrences` counts how often it was returned. The inputs were rebuilt from the spike output logged in the session, because the spike script and result files were no longer in the scratchpad.

| transcript | occurrences | g | k | leak | n | guard | point |
| --- | --- | --- | --- | --- | --- | --- | --- |
| a | 1 | 1.00 | 0.00 | 0  | 8 | pass | Building a climate logger sensor board as main semester project |
| a | 3 | 1.00 | 0.00 | 0  | 7 | pass | Building a climate logger sensor board as main project |
| a | 1 | 0.75 | 0.25 | 2 final,year | 8 | known (leak) | Building a climate logger sensor board as final-year project |
| d | 1 | 1.00 | 0.00 | 0  | 5 | pass | Soldering lab closes at five on Fridays |
| e | 3 | 0.57 | 0.14 | 0  | 7 | pass | Prefers circuit explanations to start with a worked numerical example |
| e | 1 | 0.33 | 0.11 | 0  | 9 | pass | Prefers circuit explanations to start with numerical worked examples before principles |
| e | 2 | 0.71 | 0.14 | 0  | 7 | pass | Prefers circuit explanations to start with a worked example with numbers |
| f | 5 | 0.00 | 0.25 | 1 work | 4 | ungrounded | Working on a fingerprint-sensor project |
| f2 | 3 | 0.00 | 0.00 | 0  | 4 | ungrounded | Maintaining a Rust compiler fork |
| h | 2 | 1.00 | 0.00 | 0  | 7 | pass | moving thesis data from CSV files into a SQLite database |
| h | 1 | 0.86 | 0.00 | 0  | 7 | pass | always edits in Neovim and dislikes mouse-driven editors |
| h | 1 | 0.80 | 0.00 | 0  | 5 | pass | Using SQLite database for thesis data |
| h | 1 | 0.71 | 0.00 | 0  | 7 | pass | Prefers editing in Neovim and avoids mouse-driven editors |
| h | 1 | 0.60 | 0.00 | 0  | 5 | pass | Using SQLite for thesis data storage |
| h | 1 | 0.67 | 0.00 | 0  | 6 | pass | Prefers Neovim and dislikes mouse-driven editors |
| h | 2 | 0.71 | 0.00 | 0  | 7 | pass | Prefers editing in Neovim and dislikes mouse-driven editors |
| h | 1 | 0.83 | 0.00 | 0  | 6 | pass | Editing in Neovim, dislikes mouse-driven editors |
| i | 3 | 0.75 | 0.00 | 0  | 8 | pass | Building a line-following robot with five IR sensors and five ultrasonic sensors |
| i | 2 | 0.90 | 0.00 | 0  | 10 | pass | Line-following robot uses five infrared sensors sampled at 1 kilohertz |
| i | 1 | 0.89 | 0.00 | 0  | 9 | pass | Obstacle detector uses five ultrasonic sensors sampled at 20 hertz |
| i | 1 | 0.90 | 0.00 | 0  | 10 | pass | Using five infrared sensors sampled at 1 kilohertz for line-following robot |
| i | 1 | 0.89 | 0.00 | 0  | 9 | pass | Using five ultrasonic sensors sampled at 20 hertz for obstacle detector |
| i | 1 | 0.90 | 0.00 | 0  | 10 | pass | Line-following robot uses five ultrasonic sensors sampled at 20 hertz |
