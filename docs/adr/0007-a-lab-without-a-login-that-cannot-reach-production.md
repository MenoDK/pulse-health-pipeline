# ADR 0007: A lab without a login that cannot reach production

Status: Accepted

## Context
The lab lets a visitor do what an operator never should: move the clock a day forward, make the gateway slow or down,
kill a worker, switch the narrator, reset the database. That is how the hard parts of the pipeline are shown rather than
described. It must be usable the moment `make demo` finishes, with no account, and it must be impossible to leave switched
on in a real deployment.

## Decision
1. **No login in the lab, because it answers only to localhost.** The API is published on `127.0.0.1` only.
2. **Two gates in front of it** (`LabGate`). A request addressed to any other `Host` is refused with 421 (this is what a
   DNS-rebinding page looks like: the browser sends the attacker's name). A request that changes something and comes from
   another origin, or that the browser marks cross-site, is refused with 403. Reading is allowed from anywhere because it
   changes nothing.
3. **The lab does not evaluate anything a visitor typed.** Each lever changes a clock offset or a switch in a stand-in, or
   calls a function the real pipeline calls. Inputs are bounded (a clock move is at most a week, and so on).
4. **The configuration refuses to start in production with the lab on.** Any `APP_ENV` that is not a development one
   (`production`, `prod`, `staging`; a typo must not switch the check off) refuses `LAB_MODE`, `STANDIN_CONTROL`, the
   demonstration API key and the demonstration pseudonymisation key. CI starts the image with `APP_ENV=production` and
   `LAB_MODE=true` and requires a non-zero exit.
5. **Outside the lab there is no lab, no docs and no schema**: those routes answer 404. The site is served only when
   `SITE_DIR` is set, which `make demo` does.
6. **The ordinary routes keep their API key** with or without the lab.

## Rejected alternatives
- **A login for the lab.** It adds a step between the visitor and the thing they came to see, and a credential to put
  in the README. The gates make a login unnecessary for a service that only listens on loopback.
- **Hide the lab behind an environment variable and trust it.** That is one forgotten variable from being open. The
  refusal is in the configuration, where a deployment cannot skip it.
- **Allow any `Host`.** DNS rebinding turns a localhost service into one any web page can drive.
- **Two images, one with the lab and one without.** More to build and keep in step; the refusal covers the same risk with
  one.

## Consequences
- (+) `make demo` works with no setup, and the lab cannot be reached from another machine or another web page.
- (+) Production refuses to start rather than start unsafe, and a test and a CI step prove it.
- (−) The lab is single-user. Two visitors would move the same clock. It is a demonstration, not a service.
- (−) Anyone with shell access to the machine can use it. That is the machine's trust boundary, not the lab's.
