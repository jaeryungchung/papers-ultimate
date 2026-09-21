# Toward a Narrative-adaptive Generative AI Phygital Toy: Exploring Design Strategies for Child–AI Interaction in Tabletop Play

# toy timeline
- traditional plain toy 
- interactive toy (press belly and teddy will say I love you) 
- authoring (block programming, cost, play/author time seperated) 
- dynamic adpatation to the evolving narrative (enabled by genAI)


# Abstract

Interactive toys augment physical play by sensing children's actions and providing digital feedback such as sound or light. These phygital toys aim to enrich children's play experiences by making physical interactions responsive to children's actions. Their interaction behaviors are typically governed by predefined action-response mappings: the same physical action (i.e. shaking motion) produces similar feedback (i.e. plays a song) even as children reinterpret the toy and evolve their play ~\cite{williams2024doodlebot} ~\cite{tseng2021plushpal}. This rigidity of fixed rules contrasts with the nature of open-ended pretend play~\cite{dangol2026toys}, in which children flexibly transform objects, enact roles, and develop changing play situations~\cite{cassell2001making}. Prior work has sought to make interactive toys more flexible and authorable by allowing children to define how sensed physical actions trigger digital responses. For example, sensor- and machine-learning-based systems such as PlushPal enable children to create custom gestures for physical toys and map them to personally meaningful sounds, expanding the range of interactions beyond those predefined by toy designers.~\cite{tseng2021plushpal} However, these approaches still rely on action--response mappings that are configured in advance and remain fixed as play unfolds. Advances in generative AI create an opportunity to move from such preconfigured mappings toward context-aware interactive toys that can generate and adapt their responses \textit{in situ}, as children's actions and the meaning of the ongoing play evolve.~\cite{chung2025toyteller} Define: context aware interactive 란 ~~~가 가능한 toy로 이 페이퍼에서 정의 사용, player agency 극대화 하는 ] Yet, little is known about how generative-AI-enabled context adaptation affects children's play compared with conventional fixed-response interactions, and even less is known about how initiative over such adaptation should be distributed between the child and the toy.

We present a context-aware generative AI toy (module that could be attached to a toy) that connects three representational (semantic?) spaces---physical motion, narrative context, and sound effects---to enable context-dependent sound feedback through a Motion × Narrative → Sound (S=f(M,C)) pipeline. The system uses IMU sensing to recognize physical motion and a generative-AI pipeline to maintain the evolving play context (collect talk-aloud utterance) and produce contextually appropriate sound effect responses. We first validate the system by evaluating motion recognition accuracy, context-response alignment(appropriateness/consistency?), and end-to-end interaction latency. We then conduct a within-subject study (N=20, Age 6~8) comparing fixed-response and context-adaptive versions of the same interactive toy. Through~ examining children's engagement, pretend play, and perceived control over the interaction~\cite{apsp}. Following the play sessions, we conduct a semi-structured interview to investigate when children want the toy to infer and initiate adaptations and when they want to specify, modify, or correct them. 

Our work contributes [pipeline] a sensing- and generative-AI-based technical pipeline for context-aware physical play, empirical evidence on how context adaptation changes children's interaction with an interactive toy, and design implications for distributing initiative between children and adaptive interactive toys during open-ended play.


[explicit x, utterance 인식한 narrative update] 

## Need for Adaptive (Context Aware) AI toys
'By moving beyond tightly scripted interactions, AI toys can function
less as activity managers and more as flexible play partners that
adapt to children’s evolving ideas and narratives.~\cite{dangol2026toys}'

# Research Gap

# Evaluation
Organization, Elaboration, Imagination and Comfort

# Research Question
1: How does a context-aware generative AI toy, compared with a fixed-response interactive toy, affect children's engagement and pretend play?
2: How should initiative over context adaptation be distributed between the child and the toy?