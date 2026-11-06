#!/bin/sh
# Exec check for do-work's close-source-anchor step (formula-spec-v2 section 3.1).
#
# When the workflow's require_delivery var is "true", the lane's commit (the HEAD of the
# source anchor's work_dir) must have left the host: it is on an origin branch other than
# the base branch, or it belongs to an open or merged PR. A drain item is exempt: the
# workflow that drained it publishes (build-base's publish, implement's publish).
#
# Exit 0: delivered, or delivery not required. Exit 1: not yet (reason on stdout).
# Exit 75: gc, the origin fetch or gh unreachable (no verdict).
set -u
export GIT_TERMINAL_PROMPT=0 GH_PROMPT_DISABLED=1
# gc runs exec checks with HOME set to the city, which hides the account's git and gh
# credentials; restore the account home when the host can name it.
acct_home=$(getent passwd "$(id -u)" 2>/dev/null | cut -d: -f6)
[ -n "$acct_home" ] && [ -d "$acct_home" ] && export HOME="$acct_home"

# Not a pipeline: its status would be jq's, and a gc failure would read as an empty bead.
bead() {
  j=$(gc bd show "$1" --json) || return 1
  printf '%s' "$j" | jq -ce 'if type == "array" then .[0] else . end | select(type == "object")'
}
meta() { printf '%s' "$1" | jq -r --arg k "$2" '.metadata[$k] // empty'; }
var() {
  v=$(meta "$1" "gc.var.$2")
  [ -n "$v" ] || v=$(printf '%s' "$1" | jq -r --arg k "$2" \
    '.metadata["gc.graphv2_vars.v1"] // "{}" | fromjson? | .[$k] // empty')
  printf '%s' "$v"
}
notyet() { echo "not delivered: $*"; exit 1; }

step=${GC_BEAD_ID:?GC_BEAD_ID not set}
s=$(bead "$step") || exit 75
root=$(meta "$s" gc.root_bead_id); [ -n "$root" ] || root=$step
r=$(bead "$root") || exit 75

req=$(var "$r" require_delivery)
[ "$req" = true ] || { echo "delivery not required (require_delivery='$req')"; exit 0; }
drain=$(meta "$r" gc.drain_control_id)
[ -z "$drain" ] || { echo "drain item of $drain: the draining workflow publishes"; exit 0; }

anchor=$(meta "$r" gc.source_anchor_id)
[ -n "$anchor" ] || notyet "root $root has no gc.source_anchor_id"
a=$(bead "$anchor") || exit 75
wt=$(meta "$a" work_dir)
[ -n "$wt" ] && [ -d "$wt" ] || notyet "source anchor $anchor has no worktree (work_dir '$wt')"
head=$(git -C "$wt" rev-parse -q --verify 'HEAD^{commit}' 2>/dev/null) \
  || notyet "work_dir $wt has no HEAD commit"

git -C "$wt" fetch -q origin 2>/dev/null || { echo "git fetch origin failed in $wt" >&2; exit 75; }
base=$(var "$r" base_branch)
if [ -z "$base" ]; then
  base=$(git -C "$wt" symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null | sed 's|^origin/||')
fi

# 1. A pushed branch holds the commit. A HEAD the base already holds proves nothing here (a
#    lane with no commit of its own, or one merged already), so only step 2 can pass it.
branches=
if [ -z "$base" ] || ! git -C "$wt" merge-base --is-ancestor "$head" "refs/remotes/origin/$base" 2>/dev/null; then
  branches=$(git -C "$wt" for-each-ref --contains "$head" --format='%(refname:short)' refs/remotes/origin \
    | grep -v -x -e 'origin/HEAD' -e 'origin' ${base:+-e "origin/$base"})
fi
if [ -n "$branches" ]; then
  echo "delivered: $head is on $(printf '%s' "$branches" | head -n1)"
  exit 0
fi

# 2. An open or merged PR holds the commit (a squash merge deletes the branch).
if ! gh auth token >/dev/null 2>&1; then
  notyet "$head is on no origin branch but ${base:-the base}, and gh has no credentials (HOME=$HOME) to look for a PR"
fi
prs=$(cd "$wt" && gh pr list --state all --search "$head" --json number,state) || exit 75
n=$(printf '%s' "$prs" | jq -r '[.[] | select(.state == "OPEN" or .state == "MERGED")] | .[0].number // empty')
[ -n "$n" ] && { echo "delivered: $head is in PR #$n"; exit 0; }
notyet "$head is on no origin branch but ${base:-the base} and in no open or merged PR"
