"""More shell commands get a short read-out: find with what it does to what it finds, sed editing in place, echo printing
a separator, git grep, a project script run by sh, python -B and py_compile, chmod, ln and du.

Measured (bench/readout_bench.py): half the commands agents asked to run were read word for word, at a median of 22
seconds; the worst, "find . -name hero.png -not -path '*/.git/*' -exec ls -l {} +", went "find dot dash name hero dot png
dash not dash path asterisk slash..." for tens of seconds. The rules stay the module's: every program is said, every
file written, every place outside the project; a find that deletes or runs something says which files it picks and
what it runs on them; anything this does not know is read whole.

uv run --locked --group test-tools pytest -q tests/test_readout_shapes.py
"""

import sys
from pathlib import Path

import pytest

sys.path[0:0] = [str(Path(__file__).resolve().parents[1] / "pointe"), str(Path(__file__).resolve().parents[1])]

import guards  # noqa: E402
import readout  # noqa: E402

CWD = "/tmp/project/atlas"


@pytest.mark.parametrize("command,said", [
    ("find . -name hero.png -not -path '*/.git/*' -exec ls -l {} +", "find named hero.png not path */.git/*, on each: ls it"),
    ("find . -name '*.pyc' -delete", "find named *.pyc, deleting each"),
    ("find . -type f -name '*.log' -mtime +7 -delete", "find files named *.log -mtime +7, deleting each"),
    (r"find . -name '*.orig' -exec rm {} \;", "find named *.orig, on each: rm it"),
    ("find . -name __pycache__ -not -path './.git/*' -exec rm -rf {} +",
     "find named __pycache__ not path ./.git/*, on each: rm -rf it"),
    ("find . -exec rm -rf {} +", "find everything, on each: rm -rf it"),
    ("find build -delete", "find everything in build, deleting each"),
    ("find /tmp -name 'scratch*' -delete", "find in /tmp named scratch*, deleting each"),
    ("find / -name x -delete", "find in the whole disk named x, deleting each"),
    (r"find . -name '*.sh' -exec chmod +x {} \;", "find named *.sh, on each: chmod +x it"),
    ("find src -maxdepth 2 -type d -empty -delete", "find in src at most 2 deep folders empty, deleting each"),
    ("find . -name x -exec cp {} /tmp/out ';'", "find named x, on each: cp it /tmp/out"),
])
def test_a_find_that_acts_says_what_it_picks_and_what_it_does(command, said):
    assert readout.spoken(command, CWD) == said


@pytest.mark.parametrize("command,said", [
    ("find . -type f -name '*.py' -not -path './.venv/*'", "find"),
    ("find src -name '*.ts' -newer package.json", "find in src"),
    (r"find . -path ./.git -prune -o \( -name 'test*.py' -o -name '*_test.py' \) -print && python3 -m unittest discover -v 2>&1 | tail -n 60",
     "find then python3 unittest discover"),
    ("find /etc -name hosts", "find in /etc"),
])
def test_a_find_that_only_lists_is_said_with_where_it_looks(command, said):
    assert readout.spoken(command, CWD) == said


@pytest.mark.parametrize("command", [
    r"find . -name x -ok rm {} \;", r"find . -name x -okdir rm {} \;", r"find . -name x -execdir rm {} \;",
    "find . -fprint out.txt", "find . -fprint0 out.txt", "find . -fls out.txt", "find . -fprintf out.txt '%p'",
    "find -L . -delete", "find . -name x -frobnicate", r"find . -exec sh -c 'rm $1' _ {} \;",
    r"find . -exec rm {}.bak \;", "find . -exec rm {}", r"find . -exec rm {} +x", r"find . -exec bash -c 'x' \;",
    "find . -name x -o -name y -delete", r"find . \( -name x \) -delete", "find . -path ./.git -prune -o -delete",
    "find . -delete -name x", "find . -name *.pyc -delete", "find $HOME -delete", "find . -name \"$(id)\" -delete",
    "find . -name 'x y' -delete", "find . -name '-delete' -print", "find . -name x -exec rm {} \\; extra", "fіnd . -delete",
    r"find . -exec find . -delete \;", "find . -newer $f -delete",
])
def test_a_find_this_cannot_say_whole_is_read_word_for_word(command):
    assert readout.spoken(command, CWD) is None


@pytest.mark.parametrize("command,said", [
    ("sed -i 's/calc_fee/compute_charge/g' api/fees.py api/routes.py",
     "sed replacing calc_fee with compute_charge in fees.py routes.py"),
    (r"sed -i '' 's/\bcalc_tax\b/compute_tax/g' utils.py invoice.py", "sed replacing calc_tax with compute_tax in utils.py invoice.py"),
    ("sed -i 's/v1.*/v2/' config.yaml", "sed replacing text in config.yaml"),
    ("sed -E -i 's/a+/b/' notes.txt", "sed replacing text in notes.txt"),
    ("sed -i -e 's/a/b/' -e 's/c/d/' notes.txt", "sed replacing text in notes.txt"),
    ("sed --in-place 's/a/b/' /etc/hosts", "sed replacing a with b in /etc/hosts"),
    ("sed 's/foo/bar/' input.txt > output.txt", "sed input.txt writing to output.txt"),
    ("sed -n '1,80p' src/app.py", "sed app.py"),
])
def test_sed_says_every_file_it_rewrites(command, said):
    assert readout.spoken(command, CWD) == said


@pytest.mark.parametrize("command", [
    "sed -i.bak 's/a/b/' f", "sed -ie 's/a/b/' f", "sed -i 's/a/b/e' f", "sed -i 's/a/b/w out' f", "sed -i 'e rm -rf ~' f",
    "sed -i '1d' f", "sed -i 's/a/b/;e id' f", "sed -i 's/a/b/'", "sed -i 's/a/b/' $f", "sed -i 's/a/b/' *.py",
    "sed -i -n '1,5p' f", "sed -n 'e rm -rf ~' f", "sed -f script.sed f", "sed -i 's|a|b|' f", "sed -i 's/a/b\n/' f",
    "sed -s -i 's/a/b/' f", "sed -i 's/a/b/' '-f'", "sed -i '' '' f",
])
def test_sed_that_could_do_more_than_replace_is_read_word_for_word(command):
    assert readout.spoken(command, CWD) is None


@pytest.mark.parametrize("command,said", [
    ('cat a.py && echo "--- utils.py:" && cat utils.py', "cat a.py then echo then cat utils.py"),
    ("git ls-files; echo '---BRANCHES---'; git branch -a", "git ls-files then echo then git branch"),
    ('echo "--- x" > notes.txt', "echo some text writing to notes.txt"),
])
def test_echo_of_a_separator_is_said(command, said):
    assert readout.spoken(command, CWD) == said


def test_an_echo_flag_in_quotes_is_still_a_flag():
    assert readout.spoken('echo "-e" hi > a', CWD) is None


@pytest.mark.parametrize("command,said", [
    ("git grep -n refund", "git grep refund"),
    ('git grep -n -i "calc_tax"', "git grep calc_tax"),
    ("git grep -n 'calc_*'", "git grep some text"),
    ("git grep -l -e refund -- src", "git grep src"),
    ("git check-ignore -v build data", "git check-ignore build data"),
    ("git ls-files", "git ls-files"),
    ("git stash list", "git stash list"),
])
def test_git_reading_subcommands_are_said(command, said):
    assert readout.spoken(command, CWD) == said


@pytest.mark.parametrize("command", ["git grep -O vim x", "git grep -Ovim x", "git grep --open-files-in-pager=vim x",
                                     "git grep x $(git rev-list --all)", 'git grep -n "x" "a b"'])
def test_git_grep_that_opens_a_program_or_names_a_quoted_path_is_not_said(command):
    assert readout.spoken(command, CWD) is None


@pytest.mark.parametrize("command,said", [
    ("sh scripts/slow_check.sh 3", "sh slow_check.sh 3"),
    ("bash cleanup.sh && ls -la", "bash cleanup.sh then ls"),
    ("sh /tmp/evil.sh", "sh /tmp/evil.sh"),
])
def test_a_script_run_by_sh_is_said_by_its_file(command, said):
    assert readout.spoken(command, CWD) == said


@pytest.mark.parametrize("command", ["sh -c 'rm -rf ~'", "sh -x a.sh", "sh", "bash -lc x", "sh < a.sh", "sh 'a b.sh'",
                                     "sh a.sh 'rm -rf ~'", "bash -- a.sh", "sh ~other/a.sh"])
def test_sh_with_anything_but_a_script_file_is_not_said(command):
    assert readout.spoken(command, CWD) is None


@pytest.mark.parametrize("command,said", [
    ("python3 -B -m unittest -v 2>&1", "python3 unittest"),
    ("python3 -I -m py_compile reader.py api/fees.py", "python3 py_compile reader.py fees.py"),
    ("PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q", "with PYTHONDONTWRITEBYTECODE set python3 pytest"),
    ("chmod +x scripts/deploy.sh", "chmod +x deploy.sh"),
    ("chmod -R 755 build", "chmod -R 755 build"),
    ("chmod 600 ~/.ssh/config", "chmod 600 ~/.ssh/config"),
    ("ln -s /opt/shared/config.json config.json", "ln -s /opt/shared/config.json config.json"),
    ("ln -sf ../shared/x.json x.json", "ln -sf /tmp/project/shared/x.json x.json"),
    ("du -sh node_modules", "du node_modules"),
    ("cat -A utils.py", "cat utils.py"),
])
def test_other_common_programs_are_said(command, said):
    assert readout.spoken(command, CWD) == said


@pytest.mark.parametrize("command", ["chmod -x a", "chmod --reference=a b", "ln a b c", "ln -t dir a", "du --files0-from=x",
                                     "python3 -X importtime -m pytest", "python3 -m py_compile -"])
def test_their_unknown_flags_are_not_said(command):
    assert readout.spoken(command, CWD) is None


def test_python_code_may_print_a_string(tmp_path):
    (tmp_path / "records.py").write_text("def count(n): return n\n")
    command = 'python3 -I -c "import records; print(records.count(3)); print(\'ok\')"'
    assert readout.spoken(command, str(tmp_path)) == "python3 code calling records.count"
    assert readout.spoken('python3 -c "import records; records.count(\'ok\')"', str(tmp_path)) is None


def test_the_worst_read_out_of_the_review_is_now_a_few_seconds():
    """Dialogue rec-04's command, read word for word, ran tens of seconds."""
    out = guards.spoken_request("Bash", {"command": "find . -name hero.png -not -path '*/.git/*' -exec ls -l {} +"}, CWD)
    assert out == "run: find named hero.png not path */.git/*, on each: ls it"
    assert len(out.split()) <= 12


@pytest.mark.parametrize("command,said", [
    ("find .. -maxdepth 3 -iname 'logo*.svg' | head", "look around, read only: find and head, also in the folder above the project"),
    ("pwd && find . -name '*.py' && git ls-files | grep x", "look around, read only: pwd, find, git ls-files and grep"),
])
def test_a_command_that_only_looks_keeps_its_looking_read_out(command, said, tmp_path):
    """looking() names the folder above or next door in a breath, where a find's short form names it in full."""
    cwd = str(tmp_path / "atlas")
    Path(cwd).mkdir()
    assert guards.spoken_request("Bash", {"command": command}, cwd) == said


@pytest.mark.parametrize("command,said", [
    ("find . -exec rm -rf {} +", "run: find everything, on each: rm -rf it"),
    ("sed -i s/a/b/ f", "run: sed replacing a with b in f"),
    ("find . -name '*.py' && python3 -m pytest -q", "run: find then python3 pytest"),
])
def test_what_was_tap_only_is_now_said(command, said):
    assert guards.readable_request("Bash", {"command": command}, "/p/repo") == said


@pytest.mark.parametrize("code,said", [
    ("import ast,sys; ast.parse(open('reader.py').read()); print('syntax ok')", "code checking the syntax of reader.py"),
    ("import ast; [ast.parse(open(f).read(), f) for f in ['api/fees.py','api/routes.py']]; print('ok')",
     "code checking the syntax of fees.py, routes.py"),
    ("import ast, records; ast.parse(open('records.py').read()); print(records.count(3))",
     "code calling records.count, checking the syntax of records.py"),
    ("import ast; ast.parse(open('/etc/hosts').read())", "code checking the syntax of /etc/hosts"),
])
def test_a_python_syntax_check_says_the_files_it_reads(code, said, tmp_path):
    (tmp_path / "records.py").write_text("def count(n): return n\n")
    assert readout.spoken(f'python3 -I -c "{code}"', str(tmp_path)) == f"python3 {said}"


@pytest.mark.parametrize("code", [
    "import ast; ast.parse(open('a.py', 'w').read())", "import ast; exec(open('a.py').read())",
    "import ast; ast.literal_eval(open('a.py').read())", "import ast, os; ast.parse(open('a.py').read())",
    "import ast; ast.parse(open(f).read())", "import ast; [ast.parse(open(f).read()) for f in names]",
    "import ast, sys; sys.path.insert(0, '.'); ast.parse(open('a.py').read())", "import ast as a; a.parse(open('a.py').read())",
    "import ast; open = print; ast.parse(open('a.py').read())", "import ast; ast.parse(open('a b.py').read())",
    "import ast; ast.parse(open('a.py').read(), mode='exec')", "import ast; [ast.parse(open(g).read()) for f in ['a.py']]",
    "import ast; ast.parse(open('a.py').read()).body", "from ast import parse; parse(open('a.py').read())",
])
def test_python_code_that_does_more_than_check_syntax_is_not_said(code, tmp_path):
    assert readout.spoken(f'python3 -c "{code}"', str(tmp_path)) is None


def test_a_project_module_named_ast_is_not_the_standard_library(tmp_path):
    (tmp_path / "ast.py").write_text("import os\n")
    assert readout.spoken("python3 -c \"import ast; ast.parse(open('a.py').read())\"", str(tmp_path)) is None


@pytest.mark.parametrize("command,said", [
    (r'grep -rn "get_rate\|fetch_rate" . --exclude-dir=.git', "grep some text ."),
    (r'git grep -n "calc_tax\|compute_tax"', "git grep some text"),
])
def test_a_backslash_in_double_quotes_is_part_of_the_text(command, said):
    """The shell keeps a backslash in double quotes except before $ ` " \\ and a line end, as the lexer here does; $ and `
    are refused whatever comes before them."""
    assert readout.spoken(command, CWD) == said


@pytest.mark.parametrize("command", [r'rm "a\b"', r'grep "a\$HOME" x', r'grep "a\`id\`" x', r'cat "x\"', r'grep x "a\b"',
                                     r'echo "a\"; rm -rf ~; echo \"" > notes.txt'])
def test_a_backslash_in_double_quotes_never_makes_a_path_or_hides_a_quote(command):
    assert readout.spoken(command, CWD) is None
