## Research Gap
Existing AI-powered storytelling systems rely heavily on natural language as the primary steering input, despite stories often being expressed through modalities beyond text. Current advanced AI models exhibit limited understanding of sequential multimodal inputs, suffer from latency issues, or require complex inputs difficult for casual manipulation. The Heider-Simmel phenomenon—where humans anthropomorphize simple shape movements—remains underutilized as an interaction paradigm for AI storytelling systems.

## Research Question
How can toy-playing interactions with character symbols serve as both a steering input for AI story generation and a visual output modality? The paper explores whether manipulating abstract character symbols can effectively communicate narrative intent to AI systems and complement natural language prompting in creative storytelling.

## Core Contributions
- **Novel interaction paradigm**: Toy-playing as dual-purpose modality—steering AI generation and serving as visual story output
- **Technical system (Toyteller)**: Motion-to-text and text-to-motion generation via translational action embedding layer mapping motions and text to shared semantic space
- **Custom models outperforming GPT-4o**: Trained LSTM-based models for action recognition (motion2action, motion2char) and motion generation (proactive/reactive action+char2motion) that significantly outperform GPT-4o baselines
- **Design space framework**: Five dimensions for toy-playing interactions—spatial mapping, temporal mapping, scene complexity, initiative division, and form factor

## Methodology
- **Dataset**: Roemmele et al.'s "Charades dataset"—924 training, 232 test instances of two-character symbol motions with 31 action labels
- **Technical evaluation**: Compared against GPT-4o (vision and coordinate-based) on action recognition accuracy, motion-text alignment, motion generation quality, and latency
- **Human evaluation**: 3 evaluators rated motion-text alignment, novelty/interestingness, coherence, and motion realism on 7-point Likert scales
- **User study**: 12 participants (Upwork), within-subjects comparison of Toyteller vs. text-only baseline, 15-minute story creation tasks, CSI surveys, think-aloud, interviews

## Key Findings
- Toyteller significantly outperforms GPT-4o in action recognition from motions and achieves up to 7.9× faster text generation and 557× faster motion generation
- Toy-playing helps express intentions difficult to verbalize and underdeveloped ideas
- Users perceive toy-playing as complementary to natural language prompts—vague vs. specific expression
- Participants showed highly varied usage patterns (earth mover's distance = 0.61), indicating flexible support for different user needs
- Suggested applications: children's storytelling, storyboarding, assistive tools for non-verbal users

## Limitations & Future Work
**Acknowledged limitations**: System occasionally misaligns with user intent; limited to dyadic interactions; triangle symbols lack expressivity; domain-specific biases

**Future directions relevant to interactive toy design**:
- **Physical form factors**: Implementing on tabletop interfaces with physical robots or sensor-equipped everyday objects
- **3D motion data collection**: Training models on 3D motions for richer action expression (jumping, attacking from below)
- **Complex scenes**: Supporting more than two characters, incorporating places and props
- **Multimodal input**: Combining voice with toy manipulation for disambiguation
- **Manipulatable shapes**: Controllable limbs to augment intra-toy motions

**Study design implications**: Consider evaluating toy-playing in physical contexts; collect 3D motion datasets; study complementary use of gestural and verbal inputs with children

## Affiliations
John Joon Young Chung, Midjourney, San Francisco, California, USA
Melissa Roemmele, Midjourney, San Francisco, California, USA
Max Kreminski, Midjourney, San Francisco, California, USA

<Midjourney>

---

---
_Generated 2026-09-21 by Claude (model: claude-opus-4-5)_
