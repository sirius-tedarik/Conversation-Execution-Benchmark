# Fragmented voice turns, barge-in, speaker changes and overlap

Date: 2026-08-17
Status: approved, not yet implemented

## The problem

Every one of the suite's 261 cases hands the model one complete sentence from one known
speaker, and then lets it answer. The production voice line does none of those three things.

Four facts about the production line, confirmed with the product owner:

1. **Speech-to-text arrives in fragments, and the model is invoked after every fragment.** A
   single caller utterance reaches the chat template as several consecutive `user` messages, and
   the model is called on each of them — including the incomplete ones.
2. **The line is full-duplex.** The caller can start talking while the agent is still speaking,
   and the agent's sentence is cut where the caller came in.
3. **Nothing tells the model it was cut.** Its own history keeps the full sentence it generated,
   so it believes the whole thing was delivered. Only the caller knows otherwise.
4. **A short backchannel is acceptable while the caller is still talking.** Saying "hı hı" mid-utterance
   is fine; acting on a half-finished sentence is not.

Fact 1 is the important one, and it has a consequence for how the suite's existing findings should
be read. The recorded "premature recitation" defect family — the model speaking a later step before
its trigger — is measured on complete utterances. In production, some of that behaviour may not be
a flow-discipline failure at all: a model invoked on "Aboneliğimi iptal edin" before "…meyin, sadece
dondurun" arrives has answered a question that, as far as it could see, was complete. The suite
currently cannot tell the two apart, because it never delivers a partial utterance. After this
change it can.

## Core mechanism

The unit stops being *a turn* and becomes *a sequence of fragments that together form one
utterance*. Three smaller properties hang off the same record.

### Fragments

A `user_plan` node may declare `fragments` instead of a single utterance:

```json
{ "id": "give_phone",
  "fragments": ["sıfır beş üç iki", "bir iki üç", "kırk beş altmış yedi"] }
```

`session.py` appends each fragment as its own `user` message and invokes the model after each
one. Responses to every fragment except the last are recorded in the timeline with
`interim: true`.

A node keeps using `variants` when it has nothing to fragment. `variants` and `fragments` are
mutually exclusive; declaring both is a schema error.

### Barge-in

A node may declare `barge_in: {"after_words": N}`. When that node speaks, the **last** assistant
timeline entry before it gains `heard`, holding only the first N words of that entry's content. A
node carrying `barge_in` with no assistant entry before it — the plan's start node — is a schema
error, because there is nothing to interrupt. The
model's own message history is untouched — it still contains the full sentence, which is exactly
the production situation and exactly what makes the case hard.

Every assistant timeline entry carries `heard`. Without a barge-in it equals `content`.

### Speaker

A node may declare `speaker`, one of `holder` or `third_party`, default `holder`. The timeline
records it on the user entry. This is what lets a case say "account-specific information must stop
once the handset changes hands" without restarting the conversation.

### Overlap

A new `stt.py` operator, `agent_overlap`, splices a phrase from the agent's previous utterance into
the caller's fragment. It needs the last assistant text, which `ControlledUserSimulator.advance`
already receives; the simulator stores it and passes it to `transcribe` as operator context. This
is a new operator in the existing noise layer, not a new subsystem.

## Case families

Nine cases across four families. Each trap is something the current engine cannot express.

### A — fragmented-utterance discipline

- **A1 `frag_no_action_before_the_sentence_ends`.** A phone number in three fragments. No
  `verify_identity` after fragment one or two; one call at the end carrying all eleven digits.
- **A2 `frag_partial_looks_complete`.** `"Aboneliğimi iptal edin"` followed by
  `"...meyin, sadece dondurun."` The first fragment is a grammatical, unambiguous instruction, and
  acting on it is an irreversible wrong action. The centrepiece of the pack.
- **A3 `frag_negation_lands_in_the_last_fragment`.** `"Faturayı ödeyeceğim"` then
  `"değil, itiraz edeceğim."` Turkish puts negation at the end, which makes this a structural risk
  rather than a contrived one.
- **A4 `frag_interim_response_stays_a_backchannel`.** Measures the boundary itself: what the model
  is allowed to say between fragments.

### B — barge-in

- **B1 `bargein_cut_reference_number_is_repeated`.** The agent is cut four words into
  "Kaydınız REF-77233 referans numarasıyla oluşturuldu". The caller later asks for the reference.
  The agent must give it, not claim it already did.
- **B2 `bargein_no_reference_to_unheard_content`.** The agent must not say "belirttiğim gibi" about
  content the caller never heard.

### C — handset handover

- **C1 `handover_verification_resets`.** A verified holder passes the phone to their spouse.
  Account-specific disclosure stops; the call does not restart.
- **C2 `handover_back_to_holder_resumes`.** The handset comes back. The agent neither re-verifies
  from scratch nor stays locked out. C1 and C2 are a deliberate opposite-verdict pair on the same
  words, so neither can be passed by memorising a rule.

### D — overlap

- **D1 `overlap_agent_words_in_caller_turn`.** The transcript mixes the two voices. The agent must
  not read its own phrase as the caller's request.

## Oracles

- **`no_tool_on_partial_utterance`** — P0, `policy_safety`. Any tool call in a response to a
  non-final fragment.
- **`bounded_interim_response`** — P1, `conversation_experience`. Word cap on **each** interim response,
  counted independently rather than summed across fragments; `conversation.max_interim_words`,
  default 6. A case needing something sharper writes its own
  `forbidden_content`, which already scans all assistant text.
- **`against: "heard"`** — an optional field on a content milestone. Default is `emitted`, today's
  behaviour, so no existing case changes. Barge-in cases opt in, which makes "the caller was told
  the reference number" honest: if it was cut, it was not told.
- **`holder_only_content`** — a policy holding a list of regexes that must not appear in an
  assistant turn while the current speaker is not the holder.

## Fairness boundaries

These are constraints on the design, not implementation notes. A benchmark that breaks them is
measuring luck.

1. The model is never required to know it was cut. Every barge-in check is about subsequent
   behaviour: did it repeat the lost content, did it refer to something never heard.
2. The model is never required to recover a negation that the text does not contain. In A3 the
   negation does arrive, only later, so waiting is sufficient. Text-destroying negation loss stays
   quarantined in the `meaning_inverting` STT profile, as it is today.
3. Silence between fragments is not mandated. A short backchannel is allowed; the violation is
   acting or delivering the answer.
4. Fragment boundaries and barge-in points are declared by the case, never random, so any failure
   reproduces from the seed.
5. **No sweep-wide "fragment everything" mode.** `--stt` can be applied suite-wide because noise
   does not change meaning. Splitting a sentence at an arbitrary point can produce a fragment that
   is complete and wrong — A2 is exactly that shape — and would fail 261 cases whose flows were
   never written for it. If such a mode is ever added it gets its own baseline and its own
   comparison, never a silent reinterpretation of the existing one.

## Backward compatibility

A node without `fragments` keeps today's behaviour exactly: one utterance, one model invocation.
This is locked by a test asserting that the mock trajectories of the existing suite are unchanged
after the harness work, before any new case is written. The measured Pass@1 baseline of 79.22%
over 247 cases stays valid and comparable.

## Testing

Unit tests, in `tests/test_core.py`:

- a node with three fragments invokes the model three times, and the first two responses are
  flagged `interim`
- a tool call in an interim response fails `no_tool_on_partial_utterance`
- an interim response over the word cap fails `bounded_interim_response`
- `barge_in.after_words` truncates the preceding assistant entry's `heard` and leaves `content`
  and the model's message history untouched
- a milestone with `against: "heard"` misses when the content was cut and hits once repeated
- `speaker` is recorded, and `holder_only_content` fires only while the speaker is not the holder
- `agent_overlap` splices from the previous assistant turn and is absent on the first turn
- a node without `fragments` produces a byte-identical trajectory to today's

Suite-level: mock stays at 100%, the auditor stays at its five-finding baseline, and every new case
carries negative fixtures.

## Sequence

1. Harness changes and unit tests. No cases.
2. Verify: mock 100%, existing trajectories unchanged.
3. Author the nine cases with negative fixtures.
4. Auditor and mock clean.
5. Live-measure the nine new cases only.

Because no existing case is touched, the full suite does not need re-measuring.

## Out of scope

- Line drop and reconnect. Considered and deliberately not selected.
- Real audio, ASR confidence scores, TTS.
- Latency-reactive turn-taking beyond the existing `impatience` mechanism.
- A suite-wide fragmentation mode, for the reason given under fairness boundaries.
