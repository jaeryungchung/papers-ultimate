## Research Gap
Existing interactive plush toy tools have significant limitations: they require building toys from scratch (time-intensive), destructively modifying existing toys, using specialized/custom hardware, or are limited to pre-defined gesture sets. Current physical computing platforms (MakeCode, Scratch) only offer fixed default gestures (move, shake, jump), limiting children's creative expression. The authors address this by enabling children to attach off-the-shelf hardware (micro:bit) to *existing* plush toys and design *custom* gestures using machine learning—making ML-powered gesture recognition accessible to novices through a modular, non-destructive approach.

## Research Question
- **RQ1:** How do children bring their stuffed animals to life using gestures and sound?
- **RQ2:** How did children engage with data science practices when building their ML models with PlushPal?

## Core Contributions
- **Design tool (PlushPal):** Web-based application integrating ML model building with physical toy interaction using 1NN-DTW algorithm for gesture recognition
- **Design space characterization:** 42 unique gesture types categorized (exercises, routines, play/recreation, postures, social, other)
- **Empirical findings:** Documentation of children's data sampling approaches, debugging strategies, and misconceptions about sensors/ML
- **Pedagogical insights:** Evidence that short activity shifted children's understanding of ML from "humans learning with technology" to "computers learning on their own"

## Methodology
- **System:** Web app using micro:bit accelerometer, 1NN-DTW classification, 2-second gesture samples, Web Bluetooth pairing
- **Participants:** 11 children (ages 8-14, F=6, M=5)
- **Format:** Online workshops (90 min, n=3 workshops) + in-person sessions (60 min each) due to COVID
- **Structure:** Demo → micro:bit attachment → sensor exploration → guided ML intro → brainstorming worksheet → 20 min free design → demo & interview
- **Data:** Video recordings, brainstorming worksheets, app analytics, saved ML model data, pre/post surveys
- **Analysis:** Collaborative transcript review, inductive coding, visualization of model creation timelines

## Key Findings
- Children created 42 unique gestures and 45 unique sounds (avg 4 gesture-sound pairs/project); 40% exercise-related gestures
- Two contrasting data sampling strategies observed: intentional variation (Brian Bear) vs. maximizing similarity (John Bear)
- **Key misconception:** Children believed micro:bit could detect individual limb movements of the toy
- 82% of gestures had ≤3 samples; children didn't scale sample size when adding more gesture classes
- 8/11 participants actively re-recorded samples to improve models
- Post-survey: 7/10 correctly described ML as computers learning to "recognize things on their own" (vs. 1/11 pre-survey)

## Limitations & Future Work
**Acknowledged limitations:**
- Small sample size (n=11)
- Mixed online/in-person formats may have influenced results differently
- Self-selected participants likely had high computing interest

**Future work relevant to interactive toy design/study:**
- Incorporate interface feedback about sample size as gesture count increases
- Help children understand sensor capabilities/limitations (what accelerometers can vs. cannot detect)
- Explore broader range of stuffed animal form factors to inspire different gesture types
- Test with more diverse child populations
- Longer-term studies examining sustained engagement and learning outcomes

## Affiliations
- Tiffany Tseng, Tung D. Ta, Yoshihiro Kawahara — University of Tokyo
- Yumiko Murai — Simon Fraser University
- Deanna Gelosi — University of California, Berkeley
- Natalie Freed — University of Texas at Austin

<University of Tokyo>
<Simon Fraser University>
<University of California, Berkeley>
<University of Texas at Austin>

---

---
_Generated 2026-09-21 by Claude (model: claude-opus-4-5)_
