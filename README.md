# Crossplane Examples

Below Repo is ment to help you start your journey with [Crossplane](https://www.crossplane.io/).<br>
It contains examples for creating infrastructure on Azure. <br>
It also provides [helmfile](https://helmfile.readthedocs.io/en/latest/) scripts which allows you to install and configure <br>
Crossplane in nice organized manner. We have also added tools like <br>
`direnv` and `asdf` to help you install requirements for this project. <br>
If you don't want to use them and install all dependencies your self check `.tool-versions`


## Prerequisites

You will need access to Azure subscription. <br>
You will need Azure Service Principal which will be assigned to you subscription.

## Bootsrap

* install [direnv](https://direnv.net/)
* install [asdf](https://asdf-vm.com/)
* run `direnv allow`

## Setup

#### Create kind cluster and configure it
`kind create cluster -n demo-azure`

`helmfile sync -f helmfile.yaml`

## Structure

```
.
├── cluster  -> All Needed helmfiles are here, needed for configuration
│   ├── ...
│   └── 005-xrds-helmfile.yaml -> Extend me if you add new XRD, It needs kustomize.
├── examples
│   ├── AccountAzure.yaml
│   ├── NetworkAzure.yaml
│   └── SqlAzure.yaml
├── helmfile.yaml -> Root helmfile
├── package -> Main XRDs and compositions
│   ├── account
│   ├── ....
│   └── network
│       ├── ...
│       └── subnets
│          └── ...
├── secrets.template.yaml -> Remove template and add your secrets here, for prod use External-Secters
└── sql-team -> XRDs and compositions for MSQLServer creation
    └── ...
```


## Test

Modify and  Apply examples from `/examples` folder

