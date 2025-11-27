#!/usr/bin/env python3
import os
import aws_cdk as cdk
from retro_gaming_cloud.retro_gaming_cloud_stack import RetroGamingCloudStack

app = cdk.App()

# On déploie sur ton compte par défaut, région Paris
RetroGamingCloudStack(app, "RetroGamingCloudStack",
    env=cdk.Environment(
        account=os.getenv('CDK_DEFAULT_ACCOUNT'), 
        region="eu-west-3"
    )
)

app.synth()