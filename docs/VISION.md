# Product Vision

> This repo is a week-one technical spike for a larger product. This document captures the product the spike is serving so the code and the decisions around it can be read in context. For the **technical approach, breakage response, and scaling plan** (the three rubric questions), see the [main README](../README.md).

## What we're building

**A service that preserves a person's digital presence after they die, and presents it as a living memorial page their family and community can visit.**

When someone dies, their social media goes one of two ways: their family goes through the painful, manual process of trying to download memories before accounts get memorialized or deleted, or the content slowly vanishes as platforms purge inactive accounts, links break, and CDN URLs expire. Both outcomes end the same way — a person's visible digital life evaporates within a few years.

The product's job is to make that vanishing not happen. We fetch a person's public posts, photos, and videos from the platforms they used, store the bytes in durable storage we control, and present them as a permanent, shareable memorial the family owns.

## Who it's for (MVP)

**A grieving adult family member setting up a memorial for a loved one who recently died.** Usually the next of kin — a spouse, adult child, parent, or sibling. They arrive at our product somewhere between a week and a year after the death, most often linked from a funeral home or a Google search for "preserve [person]'s Instagram."

Why this user:

- **Clear authorization signal.** Next-of-kin legally represents the deceased's digital estate in most jurisdictions. We don't have to untangle abstract consent debates — the person requesting the memorial has the right to make the request.
- **Genuine, urgent willingness to pay.** This is not a productivity tool someone tries for a week. It's a one-time, high-emotional-value purchase tied to a specific life event. Price sensitivity is low; expectations for care and reliability are high.
- **Clear referral sources.** Funeral homes, estate planners, and grief-support communities are natural first-channel partners. Nothing to invent.

Later users (out of scope for MVP): people setting up memorials for historical/cultural figures, people archiving their own accounts proactively while alive, institutions archiving public figures.

## The core tension

Instagram — and every other major platform — does not want us to do this. Their business model depends on their content staying on their site. They actively fight scrapers with rate limits, login walls, and legal threats. Official APIs don't help: Meta's Graph API only returns data for accounts that have OAuth-authorized our app, and a deceased person cannot authorize anything.

So the technical core of the product is: **reliable, durable, ethical public-data scraping, run at scale, kept alive as platforms change underneath us.** That's the problem this repo is a first attempt at.

See the [README](../README.md) for how we approach the scraping problem specifically, how the system reacts when Instagram changes or blocks us, and how the architecture evolves from one account to thousands.

## What we believe (product principles)

These are the non-obvious beliefs that should shape every future decision. When we're making a call later and these don't resolve the question, we've found a new principle and should write it down.

1. **We own the bytes, not just the links.** A digital-legacy product that relies on third-party CDN URLs is not a legacy product — the URLs expire, the platforms deprecate, and within a year the memorial is a page of broken images. Every fetch must result in bytes in our own storage. This is already the position the spike takes; see the media-rehosting section in the README.
2. **The family owns their memorial.** At any time, a family can export everything we have about their person in a standard format and take it elsewhere. No lock-in, ever. This is a product whose whole value proposition is permanence — trust has to be unconditional.
3. **Quiet before loud.** Memorial products attract tasteless design and aggressive growth tactics. We lean in the opposite direction: understated typography, no badges, no engagement loops, no "share to win." The product should feel like a well-made book, not a social feed.
4. **Platform-hostile by default.** We assume every platform will eventually block us and build the system so that a block on any single platform is a bad week, not an outage. Redundancy in scraping paths, early-warning detection, and a multi-vendor posture for the scrape layer are all first-order design choices. See README §2.
5. **One-time purchase, not subscription.** Charging monthly rent on someone's late grandmother's memory is grotesque. Price model is one-time per memorial, with optional yearly storage/support at well-below-cost pricing. This shapes how we think about per-account compute cost and justifies the media-rehosting expense up front.

## MVP shape

The minimum viable product — what gets someone from "my father died" to "here is his memorial" — needs four things:

1. **Onboarding** — A form where next-of-kin enters the person's name, optional death date, and the social handles they want preserved. Minimal, kind, fast.
2. **Scrape** — For each handle, fetch the public posts, photos, and videos. Store bytes in our object storage. (*This repo is a spike at the Instagram side of this step.*)
3. **Memorial page** — A public URL the family can share. Renders the fetched content as a chronological feed, with the person's name, dates, and optional short biography. Restrained, respectful design.
4. **Export** — One-click download of everything we have about their person as a zip of bytes + JSON metadata. Non-negotiable from day one (see principle 2).

What's explicitly **not** MVP: guestbooks, visitor condolences, live streaming funerals, multi-family accounts, private-by-default memorials, custom themes, the ability for deceased accounts to be set up pre-death, AI-generated reminiscences, chatbot-of-the-deceased features. All of these are real product directions but none of them are on the critical path from "person dies" to "memorial exists."

## 6–12 month trajectory

- **Platforms.** Add Facebook, TikTok, and YouTube in that order. Design for Twitter/X as platform-4 depending on API posture then. The scraper architecture in this repo's scale section is already shaped for sibling adapters.
- **Families.** Add multi-family-member access so siblings, grandchildren, and close friends can all view and download. Still read-only public by default.
- **Integrity.** Add the drift-detection and per-account health monitoring that §2 of the README describes as out-of-scope for this spike. This becomes critical once we have more than a handful of active memorials.
- **Distribution.** Formalize funeral-home partnerships. A "preserved by [product]" link at the bottom of an obituary page is the long-term acquisition story.

## Where this repo fits

Everything in this repository is the *scrape* step for the *Instagram* side of the *MVP*. Nothing more, nothing less. It deliberately doesn't include persistence, multi-tenancy, memorial pages, or onboarding — those are separate pieces of the product built by separate services. What this spike proves:

- We can reliably get the data out of Instagram in 2026 despite the platform's defenses.
- We have a clear answer to what happens when Instagram changes or blocks us (README §2).
- The architecture has a credible path from one account to thousands (README §3).
- We make the principled call about owning bytes vs storing URLs (README's "Why we rehost media" section).

Those four things are what a co-founder evaluating this test task should see. Everything else is context.
