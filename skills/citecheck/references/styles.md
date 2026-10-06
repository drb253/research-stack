# Citation styles — templates

One style per deliverable. Default is **APA 7** when the user does not specify. Pre-author bracketed
numbers (§) are used only by Vancouver and IEEE, numbered by first appearance in the text. Where a
field does not exist for a work (e.g. no DOI for an old book), omit it — never fabricate it.

Field mapping from the resolver record: `authors`, `year`, `title`, `container` (journal/book),
`volume`, `issue`, `pages`, `publisher`, `doi`, `url`.

---

## APA 7 (author–date; psychology, education, most sciences)

Journal article:
`Author, A. A., & Author, B. B. (Year). Title of article. *Journal Name*, *Volume*(Issue), pages. https://doi.org/10.xxxx/xxxxx`

- 1 author: `Last, F. M.`
- 2 authors: `Last, F. M., & Last, F. M.` (ampersand, inside the list)
- 3–20: all, comma-separated, `& ` before the last.
- 21+: first 19, then `... `, then the final author.
- Years: `(2021)`. No date: `(n.d.)`. Title sentence case for articles; journal title in Title Case, italic.

Example:
`Jumper, J., Evans, R., Pritzel, A., Green, T., Figurnov, M., Ronneberger, O., ... Hassabis, D. (2021). Highly accurate protein structure prediction with AlphaFold. Nature, 596(7873), 583-589. https://doi.org/10.1038/s41586-021-03819-2`

---

## MLA 9 (author–page; literature, humanities)

`Last, First, and First Last. "Title of Article." *Journal Name*, vol. X, no. Y, Year, pp. pages. https://doi.org/...`

- 1 author: `Last, First.`
- 2 authors: `Last, First, and First Last.`
- 3+ authors: `Last, First, et al.`

---

## Chicago (notes–bibliography, bibliography form; history)

`Last, First. "Title of Article." *Journal Name* Volume, no. Issue (Year): pages. https://doi.org/...`

- 2 authors: `Last, First, and First Last.`
- 3+ (≤10): `Last, First, Second Last, and Third Last.`
- 11+: first author `et al.`

---

## Vancouver (numbered, biomedical)

`Author FAMILYINITIALS. Title. Journal. Year;Volume(Issue):pages.`

- Initials without periods or spaces (`Smith JA`).
- Up to 6 authors listed; 7+ → first 6 then `et al.`
- Numbered in text as `(1)` or superscript; the list is numbered in citation order.

Example:
`1. Jumper J, Evans R, Pritzel A, Green T, Figurnov M, Ronneberger O, et al. Highly accurate protein structure prediction with AlphaFold. Nature. 2021;596(7873):583-589. doi:10.1038/s41586-021-03819-2`

---

## IEEE (numbered, engineering/CS)

`[n] F. M. Last and G. H. Last, "Title of paper," *Journal Name*, vol. X, no. Y, pp. pages, Year.`

- Initials before surname, with periods (`A. B. Author`).
- `and` before the last of up to six names; 7+ → first name `et al.`

---

## Harvard (author–date, UK variants)

`Author, A.A. (Year) 'Title of article', *Journal Name*, Volume(Issue), pp. pages. doi:10.xxxx/xxxxx`

- `&` between two authors; `et al.` for four or more in some variants — match what the user's style sheet shows.

---

## BibTeX

```bibtex
@article{key2021word,
  author  = {Last, First and Other, Second},
  title   = {Title of article},
  journal = {Journal Name},
  year    = {2021},
  volume  = {596},
  number  = {7873},
  pages   = {583-589},
  doi     = {10.1038/s41586-021-03819-2}
}
```

- Entry type: `@article` (journal), `@inproceedings` (conference), `@book`, `@misc` (preprint).
- Authors joined with ` and `; each as `Last, First`.
- Citation key: `firstauthorfamily` + `year` + first significant title word, all lowercase, letters only
  (e.g. `jumper2021highly`). The bundled script emits this key so entries from different sources dedupe.
- A retracted work gets `note = {RETRACTED}`.

---

## Choosing the numbered styles

Vancouver and IEEE put a number before each entry. Assign numbers in **order of first appearance in the
text**, not alphabetical order, and reuse the same number for a repeated citation.
