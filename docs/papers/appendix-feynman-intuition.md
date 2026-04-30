# Appendix: Feynman Intuition

A companion to *Thermodynamic Memory vs. Flat Importance*. Three explanations, each shorter. If the main paper is the proof, this appendix is the picture you can hold in your head while reading it.

---

## 1. The Library Analogy

Imagine two libraries. Each holds a million books. They were stocked from the same catalog on the same day.

**Library A** is a warehouse. Every shelf is the same height. Every book has the same priority. There is no librarian. When you walk in and ask, "I need a book about the French Revolution," a clerk runs a keyword search across all million spines and brings back every book that matches. There are five thousand of them. They land on the desk in a heap. The clerk shrugs. He cannot tell you which is the best one, because in Library A there is no "best." Every book was filed with the same care, which is to say, with no care at all about which mattered more. You take the top of the pile. It is a pamphlet from 1953 that mentions the Revolution in passing. The book you actually wanted, the one half the patrons have read and recommended for forty years, is somewhere in the heap, but you would have to read all five thousand to find it.

**Library B** has a librarian. She watches. When a patron borrows a book, she notices. When ten patrons borrow the same book in a week, she walks it down to a special shelf at the front of the building, near the door, where the light is good and the chairs are comfortable. When a book sits untouched for a year, she carries it to the basement. When it sits untouched for ten years, she carries it deeper, past the boiler, into a back room where retrieval takes ten minutes and a flashlight. She is not throwing books away. She is changing how easy each one is to reach, based on whether anyone has reached for it lately.

Now the same patron walks into Library B and asks for a book about the French Revolution. The librarian does not run a keyword search across a million books. She glances at the front-of-house shelf, sees three French-Revolution books that have been borrowed twice this month, and hands the patron the most-borrowed one. Total time: four seconds. The patron reads it. It is, in fact, the best book. Not because the librarian is smart, but because *thousands of previous patrons already did the work of figuring out which book was best*, and the librarian is just letting their behavior shape the shelf.

Same data. Same query. Different recall structure. Library A returns *any* matching book with equal probability — useless when the patron only has time for one. Library B returns the book the collective has already validated.

Now translate. Cortex is Library B. The translation is direct.

- **Heat** is front-of-house placement. A memory that gets retrieved, referenced, or built upon gets warmer. A warm memory is closer to the door.
- **Decay** is the slow walk to the basement. A memory that nobody touches for a long time cools. It is not deleted. It is just further away — it costs more to retrieve, and it has to compete harder against fresher memories to surface.
- **The predictive coding gate** is the librarian at the donation desk. When someone tries to donate a near-duplicate of a book the library already has, she politely refuses. The library does not need a fifth copy of the same pamphlet under a different title. The gate checks whether the incoming memory is genuinely new information or just a restatement of something already shelved.
- **Consolidation** is what the librarian does on quiet nights. She takes ten cold books on the same topic, writes a single summary index card that captures what was important across all of them, files the card in the active catalog, and moves the original ten to deep archive. The information is preserved; the access pattern is changed. What used to be ten lookups is now one.

The whole architecture is a mechanical answer to a single question: *given that you cannot read everything, what should be easy to reach?* Library A refuses to answer the question. Library B answers it continuously, by watching what gets used.

---

## 2. The Party-Table Analogy

You walk into a noisy party. You need to find the one friend who knows about, say, the structural failure modes of suspension bridges. You have two strategies.

**Strategy 1.** You shout the topic across the room. Everyone who has ever heard of suspension bridges raises a hand. Fifty hands go up. Some belong to civil engineers. Some belong to people who watched a documentary in 2009. Some belong to a person who once drove across the Golden Gate. The hands all look identical from across the room. You walk toward the nearest one and hope. This is keyword search over a flat memory. It returns matches. It cannot tell you which match is worth your time.

**Strategy 2.** Same shout, same hands, but now each raised hand glows. The brightness of the hand is proportional to how recently and how seriously that person has engaged with the topic. The civil engineer who has been arguing about cable tension for the last hour is glowing white-hot. The 2009-documentary watcher is a faint amber. The Golden Gate driver is barely visible. You walk to the brightest hand. It takes two seconds. You get the engineer.

That is what heat does to retrieval. It does not change *who knows what*. It changes *who is easy to find*. The information content of the room is identical in both strategies. The difference is whether the room tells you, at a glance, which person to talk to first.

WRRF — the fusion math the main paper describes — is the formal version of "brightness." It combines several signals (how well the topic matches, how recently the person engaged, how often the person has been useful before) into a single brightness value. Heat is one of those signals, and it is the one that grows from use and fades from disuse, exactly like the glow on the engineer's hand.

You do not have time to interview fifty people. The room has to help you choose. A flat memory cannot help. A thermodynamic memory does.

---

## 3. The Freshman One-Line Summary

If everything is equally important, nothing is. Cortex makes memories compete for attention over time. The ones that earn attention through use stay easy to find. The ones that don't fade naturally — which is exactly what your brain does, and exactly why your brain doesn't crash with seventy years of memories.
