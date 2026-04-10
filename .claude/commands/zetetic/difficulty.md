# Quick Difficulty Check

Show the current state of all difficulty books. Flag the hardest unaddressed case.

## Instructions

1. Run `tools/difficulty-book-manager.sh status` to show all books.

2. Run `tools/difficulty-book-manager.sh check` to identify any blocked books (hardest case open).

3. For each blocked book, show the hardest-case entry and ask the user if they want to address it now.

4. If no difficulty books exist, suggest creating one for the current design/theory with `tools/difficulty-book-manager.sh create <name>`.

$ARGUMENTS
