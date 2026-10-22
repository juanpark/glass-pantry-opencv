"""Architecture diagram for the competition engine. Re-run after any architecture change:

    uv run --with diagrams python docs/architecture/architecture.py
"""

from diagrams import Cluster, Diagram, Edge
from diagrams.aws.compute import ECR, Lambda
from diagrams.aws.database import Dynamodb
from diagrams.aws.management import CloudwatchLogs, SystemsManagerParameterStore
from diagrams.aws.security import IAMRole
from diagrams.generic.blank import Blank
from diagrams.generic.device import Mobile
from diagrams.onprem.vcs import Github

G = {"size": "16,9!", "ratio": "compress", "dpi": "220", "nodesep": "0.7", "ranksep": "1.0",
     "fontname": "Helvetica", "fontsize": "15", "pad": "0.4"}
N = {"fontname": "Helvetica", "fontsize": "13"}
E = {"fontname": "Helvetica", "fontsize": "11", "color": "#7a8580"}


def step(label):
    return Blank(label, shape="box", style="rounded,filled", fillcolor="#e3f0eb", color="#1f6f5c", width="2.1",
                 height="0.7", fixedsize="false", labelloc="c")


with Diagram("Glass Pantry Shelf Check", filename="docs/architecture/architecture", outformat="png", show=False,
             direction="LR", graph_attr=G, node_attr=N, edge_attr=E):
    person = Mobile("Person\n(web page or app)")

    with Cluster("AWS us-east-1", graph_attr={"bgcolor": "#f3f6fb", "fontname": "Helvetica"}):
        with Cluster("Lambda container: OpenCV 5 + agent loop", graph_attr={"bgcolor": "#ffffff"}):
            gate = step("1 Photo gate\n(OpenCV: blur, shake, light)")
            read = step("2 Model reads shelf\n(items, boxes, shelf edges)")
            planes = step("3 Shelf check\n(OpenCV: Canny + Hough)")
            zsel = step("4 Pick close-ups\n(OpenCV: size, sharpness, edge)")
            zread = step("5 Close-up re-read\n+ label judge")
            decide = step("6 Decide\nfile / ask / retake")
            gate >> Edge(label="sharp") >> read >> planes >> zsel >> zread >> decide
            gate >> Edge(label="blurry: retake,\nno model call", style="dashed") >> decide
        counter = Dynamodb("Daily scan\ncounter")
        params = SystemsManagerParameterStore("On/off switch\n+ API key")
        logs = CloudwatchLogs("Logs\n(codes, counts only)")
        repo = ECR("Engine image")

    claude = Blank("Anthropic API\nClaude Opus 5.5 (vision)\nHaiku 5.5 (judge)", shape="box", style="rounded,filled",
                   fillcolor="#fbf1dc", color="#8a5a00", width="2.6", height="0.9", fixedsize="true", labelloc="c")

    with Cluster("Deploy (no stored keys)", graph_attr={"bgcolor": "#fbf6ec", "fontname": "Helvetica"}):
        gh = Github("GitHub Actions\nmain branch")
        role = IAMRole("Deploy role\n(OIDC, 1 h)")

    person >> Edge(label="photo") >> gate
    decide >> Edge(xlabel="list, questions, overlays", constraint="false", color="#1f6f5c") >> person
    params >> Edge(style="dotted") >> gate
    counter >> Edge(label="admit", style="dotted") >> gate
    read >> Edge(label="1 call") >> claude
    zread >> Edge(label="≤ 4 + 4 calls") >> claude
    decide >> Edge(style="dotted") >> logs
    gh >> Edge(label="OIDC token") >> role >> Edge(label="push image,\nupdate stack") >> repo
