# Skill: Puzzles and Games - A Mathematical Modeling Approach (Hürlimann, 6th ed.)

Source: Tony Hürlimann, "Puzzles and Games: A Mathematical Modeling
Approach", 6th edition, July 2025, ISBN 978-0-359-27269-3, 420 pp.
PDF received from the user 2026-11-25 (digital pdfTeX text, clean
extraction, no OCR gate needed). Read in two passes: (1) full
structure (ch.2 math puzzles, ch.3 chessboard placements, ch.4 logical
puzzles, ch.5 other puzzles/games - 97 worked LPL models), (2) deep
read of the ten sections distilled below (chess1, chess4, chess5,
einstein, alcuin, golomb, sendmore, change, SevenEleven, magicsq,
sudoku).

This is The-brain's reference for turning recreational puzzles into
exact constraint models. Apply it whenever a puzzle, brain-teaser or
game shows up as an optimization task: the modeling moves below
(boolean propositions linearized as sums, total vs ordinary domination,
time-indexed state transitions, aggregate safety cuts, product
constraints with symmetry breaking) transfer directly to industrial
models. Implemented in packages/brain-core/brain_core/puzzles/
(chess.py, logic.py, numeric.py), tested in tests/test_puzzles.py.

## 1. Chessboard placement (ch.3)

- Domination models are boolean covering formulas, linearized 1:1 as
  sum >= 1. The decisive modeling question is whether a piece covers
  its OWN square:
  - chess1 Knight Domination (sec 3.1): the book's constraint ORs only
    the up-to-8 attacking positions, never x[i,j] itself. Every square,
    occupied or not, must be ATTACKED - graph-theoretic TOTAL
    domination. 8x8 answer: 14 knights (ordinary domination would be
    12; confusing the two is the classic modeling error here, and our
    first implementation made exactly that mistake - caught by the
    locked-value test).
  - chess4 Queen Placement I (sec 3.4): ordinary domination; the
    book's row/column ORs include h=i, so an occupied square counts as
    covered. 8x8 answer: 5 queens.
  - chess5 Queen Placement II (sec 3.5): independence, at most one per
    row/column/diagonal. 8x8 answer: 8 queens; 92 distinct maximal
    solutions (enumeration by fixing the objective at the optimum,
    clearing it, and enumerate_all_solutions).
  - Diagonal constraints: main diagonals i-j=d need d in -(n-1)..n-1,
    but ANTI-diagonals i+j=s need s in 0..2n-2. Reusing the main range
    silently leaves half the anti-diagonals unconstrained (our second
    caught bug - it inflated the 8-queens count from 92 to 412).

## 2. Logic puzzles (ch.5)

- einstein (sec 5.1): five permutations over houses 1..5 (nationality,
  color, pet, drink, cigar), one int var per value, alldifferent per
  category, 15 rules as equalities or adjacency disjunctions. Encode
  |u-v|=1 as add_abs_equality with the target's domain FIXED to {1} -
  a target domain of [1,4] only forces u != v and silently changes the
  solution (our third caught bug). Book variant: drinks
  coffee/tea/milk/juice/water, cigars Dunhill/Marlboro/Pall-Mall/
  Bluemaster/Prince. Unique solution; the German owns the fish.
- alcuin Wolf-Goat-Cabbage (sec 5.2): time-indexed binaries
  x/y/z (left bank / on boat / right bank) over t=0..T, T=2*5-1=9 from
  the at-most-5 left-bank configurations argument. Transitions split
  by parity: even t ships left-to-right, odd t ships right-to-left;
  at most one item per shipment; minimize sum(x) (empty the left bank
  as early as possible). Safety constraints are asymmetric in the
  book: left bank uses the pairwise exclusions x_w+x_g<=1, x_g+x_c<=1,
  but the right bank uses the aggregate CUTS z_g+z_c-z_w<=1,
  z_w+z_g-z_c<=1, which block exactly the two unsafe pairs while
  allowing (1,1,1) - needed so the man can return empty once
  everything is across. Using pairwise cuts on the right bank forces a
  spurious extra shuttle (our fourth caught bug). Locked answer: 7
  crossings (goat; empty back; cabbage; goat back; wolf; empty back;
  goat).
- sendmore (sec 5.9): alphametic; alldifferent digits, leading digits
  nonzero, one linear equation. Unique: 9567+1085=10652.
- change (sec 2.27): 50a+25b+10c+5d+e=115 with a,b,d<=1, c,e<=4.
  Unique: (1,1,4,0,0) - the point of the puzzle is that "change for a
  dollar" has exactly one solution under the vending constraints.

## 3. Numeric and grid puzzles

- SevenEleven (sec 2.28): four prices in cents, sum 711, product
  711*10^6. Model the product with chained multiplication equalities
  (p1=x*y, p2=p1*v, p2*w=BIG) and break symmetry by ordering the
  prices. Unique: {120,125,150,316} ($1.20+$1.25+$1.50+$3.16=$7.11).
- golomb (sec 5.4): marks at integer positions, all pairwise distances
  distinct (alldifferent over the n(n-1)/2 distance vars), minimize
  the last mark. Translation/reflection symmetry broken by m0=0 and
  strict ordering. Locked: G(4)=6, G(5)=11, G(6)=17.
- magicsq (sec 5.24): n x n alldifferent over 1..n^2, all line sums
  equal. The constant is forced: n(n^2+1)/2 = 15 for n=3 (8 solutions
  up to symmetry).
- sudoku (sec 5.27): the book's binary formulation x[i,j,k], one
  number per cell, each number once per row/column/3x3 block. The
  book's givens are an image (Figure 5.69), so the implementation is
  the general solver and the test uses a standard published puzzle
  with a known unique solution - noted as a standard fixture, not a
  book-locked value.

## 4. Modeling lessons worth keeping

- A puzzle's answer is only as good as the reading of its constraint.
  Four of ten models initially encoded a plausible-but-wrong variant
  (ordinary vs total domination, anti-diagonal range, adjacency
  encoding, right-bank cuts). Locked book values plus independent
  validators caught every one.
- Symmetry breaking (ordering prices, ordering marks, m0=0) is what
  makes product/Golomb models solve in milliseconds.
- Enumeration pattern: solve with objective, fix the objective value,
  clear the objective, enumerate_all_solutions with a counting
  callback.
- Time-indexed formulations need a horizon argument (alcuin's
  5-configurations -> T=9), and the "obvious" safety constraints may
  need to be cuts, not pairwise exclusions, to stay feasible at the
  end state.
