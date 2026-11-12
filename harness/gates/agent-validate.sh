#!/usr/bin/env bash
# Gate: compila con Agentforce DX cada authoring bundle (Agent Script) tocado por la feature.
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"
need sf "npm install -g @salesforce/cli"

read_items < <(changed_existing | grep -E '/aiAuthoringBundles/[^/]+/' \
                         | sed -E 's#.*/aiAuthoringBundles/([^/]+)/.*#\1#' | sort -u)
if [ "${#ITEMS[@]}" -eq 0 ]; then
  echo ". La feature no toca authoring bundles (aiAuthoringBundles/)."
  summary "sin authoring bundles que validar"; exit 0
fi

fail=0
for b in "${ITEMS[@]}"; do
  echo "\$ sf agent validate authoring-bundle --api-name $b --target-org $HX_TARGET_ORG"
  sf agent validate authoring-bundle --api-name "$b" --target-org "$HX_TARGET_ORG" || fail=$((fail + 1))
done
if [ "$fail" -gt 0 ]; then summary "$fail de ${#ITEMS[@]} bundle(s) no compilan"; exit 1; fi
summary "${#ITEMS[@]} bundle(s) validados"
