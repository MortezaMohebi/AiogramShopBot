#!/usr/bin/env bash
# Install pinned upstream Agent Skills into this repository's local skill directory.
# The upstream code is never executed by this installer.
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd -P)"
VENDOR_DIR="$ROOT_DIR/.agent-skill-vendors"
SKILLS_DIR="$ROOT_DIR/.agents/skills"

SUPERPOWERS_REF="2ce8aa15d05bd57213e6f746f953aafb7ded7a8b"
AWESOME_REF="58ea4e8915de64907d04cc909a1b8c6e5cf0fcb7"

if ! command -v git >/dev/null 2>&1; then
    echo "ERROR: Git is required to install Agent Skills." >&2
    exit 1
fi

mkdir -p -- "$VENDOR_DIR" "$SKILLS_DIR"

install_repository() {
    local name="$1"
    local url="$2"
    local commit="$3"
    local destination="$VENDOR_DIR/$name-$commit"
    local temporary

    if [[ -d "$destination/.git" ]]; then
        if [[ "$(git -C "$destination" rev-parse HEAD)" != "$commit" ]]; then
            echo "ERROR: Unexpected Git revision in $destination" >&2
            return 1
        fi
        printf '%s\n' "$destination"
        return 0
    fi

    if [[ -e "$destination" || -L "$destination" ]]; then
        echo "ERROR: Existing vendor path is not a valid checkout: $destination" >&2
        return 1
    fi

    temporary="$(mktemp -d "$VENDOR_DIR/.$name.XXXXXX")"
    if ! git clone --quiet --no-checkout --depth 1 "$url" "$temporary" ||
       ! git -C "$temporary" fetch --quiet --depth 1 origin "$commit" ||
       ! git -C "$temporary" checkout --quiet --detach "$commit"; then
        rm -rf -- "$temporary"
        echo "ERROR: Could not fetch pinned revision of $name." >&2
        return 1
    fi

    if [[ "$(git -C "$temporary" rev-parse HEAD)" != "$commit" ]]; then
        rm -rf -- "$temporary"
        echo "ERROR: Upstream commit did not match pinned revision." >&2
        return 1
    fi

    mv -- "$temporary" "$destination"
    printf '%s\n' "$destination"
}

link_skills() {
    local checkout="$1"
    local source destination previous
    local count=0

    for source in "$checkout"/skills/*; do
        [[ -f "$source/SKILL.md" ]] || continue
        destination="$SKILLS_DIR/$(basename -- "$source")"

        if [[ -L "$destination" ]]; then
            previous="$(readlink -- "$destination")"
            if [[ "$previous" == "$source" ]]; then
                count=$((count + 1))
                continue
            fi

            # Replace only symlinks created from our pinned vendor directory.
            case "$previous" in
                "$VENDOR_DIR"/superpowers-*/skills/*|"$VENDOR_DIR"/awesome-agent-skills-*/skills/*)
                    rm -- "$destination"
                    ;;
                *)
                    echo "ERROR: Refusing to replace custom skill: $destination" >&2
                    return 1
                    ;;
            esac
        elif [[ -e "$destination" ]]; then
            echo "ERROR: Refusing to replace custom skill: $destination" >&2
            return 1
        fi

        ln -s -- "$source" "$destination"
        count=$((count + 1))
    done

    if [[ "$count" -eq 0 ]]; then
        echo "ERROR: No valid SKILL.md files found in $checkout" >&2
        return 1
    fi
    echo "Linked $count skills from $(basename -- "$checkout")."
}

superpowers="$(install_repository "superpowers" "https://github.com/obra/superpowers.git" "$SUPERPOWERS_REF")"
awesome="$(install_repository "awesome-agent-skills" "https://github.com/khasky/awesome-agent-skills.git" "$AWESOME_REF")"

link_skills "$superpowers"
link_skills "$awesome"

# Check the two entry points after creating links.
test -f "$SKILLS_DIR/using-superpowers/SKILL.md"
test -f "$SKILLS_DIR/awesome-bug-fix/SKILL.md"
echo "Agent Skills installed in $SKILLS_DIR"
