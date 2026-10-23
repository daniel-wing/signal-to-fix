# To do (after the demo)

1. **Category governance.** Categories come from a fixed list in `prompt.txt`, so the model cannot create "Card declined" next to "Declined card". The open question is how the list grows: a person reviews the Emerging cases, names a new category, and adds it to the list with an owner. Define who approves a new category, how often the list is reviewed, and how old cases are re-labeled.
2. **Held-out test set.** Masking and risk words were tuned on the same 60 cases they are scored on. Build a fresh set the tuning never saw.
3. **Human-human agreement.** Two reviewers label the same cases blind, to know what accuracy is good enough (Gate 0).
4. **Root cause (4P) quality.** Top P matches the label only about half the time, mostly Process vs Product. Write clearer definitions with the process owners, then re-test.
5. **Model-side risk flag** as a second net behind the risk word list (eval run 1 showed the list misses paraphrases).
6. **Portuguese** conversations for Brazil.
7. **Relabel C008 and C047** in `cases_raw.json` as review: they are repeat contacts.
