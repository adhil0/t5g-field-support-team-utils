#!/bin/bash

set -ex

IMAGE=t5gweb
NS=t5g-web
TAG=${1:-latest}
PUSH=${2:-false}
BASE=${3:-false}

if [[ $BASE == "true" ]]; then
  container=$(buildah from registry.fedoraproject.org/fedora:37)
  echo "building container with id $container"
  buildah config --label maintainer="David Critch <dcritch@redhat.com.com>" $container
  buildah run $container dnf -y install python3-pip gcc redhat-rpm-config python3-devel npm
  buildah copy $container ../src/ /srv/
  buildah config --workingdir /srv $container
  buildah run $container pip3 install .
  buildah run $container npm ci --prefix t5gweb/static
  buildah config --port 8080 $container
  buildah commit --format docker $container $IMAGE-base:$TAG
  buildah tag $IMAGE-base:$TAG $IMAGE:$TAG
else
  container=$(buildah from localhost/$IMAGE-base:$TAG)
  echo "building container with id $container"
  buildah config --label maintainer="David Critch <dcritch@redhat.com.com>" $container
  buildah copy $container ../src/ /srv/
  buildah config --workingdir /srv $container
  buildah config --port 8080 $container
  buildah commit --format docker $container $IMAGE:$TAG
fi

if [[ $PUSH == "true" ]]; then
  REGISTRY=${REGISTRY:-$(oc get route/default-route -n openshift-image-registry -o json | jq -r .spec.host)}
  echo pushing to $REGISTRY
  buildah tag $IMAGE:$TAG $REGISTRY/$NS/$IMAGE:$TAG
  buildah login -u $(oc whoami) -p $(oc whoami -t) --tls-verify=false $REGISTRY
  buildah push --tls-verify=false $REGISTRY/$NS/$IMAGE:$TAG
  oc delete pod -l app=t5gweb-tasks
  for pod in $(oc get pods -l app=t5gweb-app --no-headers | awk '{print $1}'); do oc delete pod/$pod; sleep 15; done # rolling update
fi
