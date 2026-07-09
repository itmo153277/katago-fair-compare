# katago-fair-compare

An analysis engine that helps compare different moves fairly (to the extent that
is possible) using KataGo.

## Motivation

KataGo is a very useful tool for analyzing Go games. However, it can be hard to
know how to interpret its output. When comparing moves, which metric is best to
use: score lead or win rate? How many visits are needed to estimate these values
accurately? This program helps address all of those questions.

## FAQ

### Why does the program force single-threaded search?

Multi-threaded search is generally weaker than single-threaded search given the
same number of visits.

### Why use assumed komi instead of the one from the game?

KataGo's search behaves differently depending on who is ahead. The only way to
ensure that the strongest moves are being searched is to make it believe that
the game is even.

### What is weight? Why use it instead of visits?

Not all visits are equal. KataGo estimates how accurate its evaluations are for
each visit. That uncertainty is taken into account by using weights instead of
raw visits.

### What is radius?

Radius shows how large the variance of the utility score is. The larger the
radius, the greater the variance.

### Why use utility score as the target metric?

Utility score is what KataGo uses during search. It includes estimates of
win rate, final score, and its variance. Because the evaluation is based on an
"even" position thanks to adjusted komi, this is a strong metric for comparing
moves.
