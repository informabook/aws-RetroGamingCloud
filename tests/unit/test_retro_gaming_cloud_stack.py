import aws_cdk as core
import aws_cdk.assertions as assertions

from retro_gaming_cloud.retro_gaming_cloud_stack import RetroGamingCloudStack

# example tests. To run these tests, uncomment this file along with the example
# resource in retro_gaming_cloud/retro_gaming_cloud_stack.py
def test_sqs_queue_created():
    app = core.App()
    stack = RetroGamingCloudStack(app, "retro-gaming-cloud")
    template = assertions.Template.from_stack(stack)

#     template.has_resource_properties("AWS::SQS::Queue", {
#         "VisibilityTimeout": 300
#     })
