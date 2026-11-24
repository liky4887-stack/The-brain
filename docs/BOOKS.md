# Reference material and honesty note

The user supplied a reading list as TITLES ONLY (docs/notes-01). No book
files were provided for this project, and no unauthorized copies were used.

Not available to the build (titles only): Williams, Model Building in
Mathematical Programming; Bertsimas & Tsitsiklis; Wolsey; Chen/Batson/Dang;
Apt; the CP Handbook; the CPAIOR volume; MO-Book.

Used instead, all public and lawful:
- Google OR-Tools documentation and examples (developers.google.com/
  optimization), specifically the CP-SAT scheduling guide (interval
  variables, AddNoOverlap, integer-only coefficients).
- The CP-SAT Primer, Dominik Krupke (d-krupke.github.io/cpsat-primer,
  public).
- Pyomo and HiGHS documentation (for the later MILP adapter).
- The user's own six research documents (docs/plan-beating-dios.txt,
  docs/notes-0*.txt), whose performance claims are treated as directional
  until verified against primary sources.

Every formulation decision in code cites the doc it came from in a header
comment. Where the unavailable books would have been the authority
(formulation strength, big-M traps), the weaker public sources are flagged
at the point of use instead of being silently borrowed.
