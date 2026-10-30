"""The checker catches every kind of mistake a hand-written row can have."""

from chanakya.neural.human_set import COLUMNS, load, problems

HEADER = ",".join(COLUMNS) + "\n"


def write(tmp_path, body: str):
    path = tmp_path / "lines.csv"
    path.write_text(HEADER + body, encoding="utf-8")
    return path


def test_a_good_file_has_no_problems_and_loads_concern_lists(tmp_path):
    path = write(tmp_path, '"kiraya kitna, aur hidden charge?",rental_cost;hidden_charges,hinglish,hinglish_roman,gurnoor\n'
                           "koi problem nahi hai,none,hinglish,negation,durvish\n")
    assert problems(path) == []
    assert [r["concerns"] for r in load(path)] == [["rental_cost", "hidden_charges"], []]


def test_bad_rows_are_reported_with_their_line_numbers(tmp_path):
    path = write(tmp_path, "haan ji,rental_cost,hinglish,no_worry,gurnoor\n"
                           "haan ji,none,hinglish,no_worry,gurnoor\n"
                           "kuch bhi,price_worry,tamil,misc,\n"
                           "ਹਾਂ ਜੀ,none,hindi,punjabi,durvish\n")
    found = problems(path)
    assert "line 2: a no_worry line must have concerns none" in found
    assert "line 3: duplicate text" in found
    assert any(p.startswith("line 4: unknown concern") for p in found)
    assert any(p.startswith("line 4: language") for p in found) and any(p.startswith("line 4: slice") for p in found)
    assert "line 4: author is required" in found
    assert "line 5: the punjabi slice needs language punjabi" in found


def test_a_wrong_header_stops_the_check(tmp_path):
    path = tmp_path / "lines.csv"
    path.write_text("text,label\nhello,none\n", encoding="utf-8")
    assert problems(path) == ["header must be " + ",".join(COLUMNS)]
