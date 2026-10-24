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
     "fontname": "Helvetica", "fontsize": "15", "pad": "0.4", "splines": "spline"}
N = {"fontname": "Helvetica", "fontsize": "13"}
E = {"fontname": "Helvetica", "fontsize": "11", "color": "#7a8580"}


def step(label):
    return Blank(label, shape="box", style="rounded,filled", fillcolor="#e3f0eb", color="#1f6f5c", width="2.1",
                 height="0.7", fixedsize="false", labelloc="c")


with Diagram("Glass Pantry: photo to fridge twin", filename="docs/architecture/architecture", outformat="png", show=False,
             direction="LR", graph_attr=G, node_attr=N, edge_attr=E):
    person = Mobile("Person\n(phone or computer browser)")

    with Cluster("Browser: your fridge (kept in this browser, on this device)", graph_attr={"bgcolor": "#f6f3fb", "fontname": "Helvetica"}):
        pick = step("A Pick the fridge\n(app catalogue layouts)")
        outline = step("B Outline the opening\n(named corners, edges;\nshelves in perspective)")
        twin = step("D Fridge twin\nlevels, items, Unplaced\n+ last photo of each shelf")
        pick >> twin

    with Cluster("AWS us-east-1: one Lambda container (OpenCV 5 on CPU, 4096 MB)", graph_attr={"bgcolor": "#f3f6fb", "fontname": "Helvetica"}):
        with Cluster("Identify: POST /identify (1 model call)", graph_attr={"bgcolor": "#ffffff"}):
            igate = step("Photo gate\n(OpenCV: blur, shake)")
            iread = step("Model reads the sticker\n(code, maker, kind)")
            imatch = step("Code matches the catalogue\nexact / family / kind")
            igate >> Edge(label="sharp") >> iread >> imatch
        with Cluster("Set up: POST /straighten (no model call)", graph_attr={"bgcolor": "#ffffff"}):
            warp = step("C Check + straighten\n(OpenCV: quad checks,\nwarpPerspective)")
        with Cluster("Fill: POST /scan, OpenCV 5 + agent loop", graph_attr={"bgcolor": "#ffffff"}):
            gate = step("1 Photo gate\n(OpenCV: blur, shake, light)")
            read = step("2 Model reads shelf\n(items, boxes, shelf edges)")
            planes = step("3 Shelf check\n(OpenCV: Canny + Hough)")
            zsel = step("4 Pick close-ups\n(OpenCV: size, sharpness, edge)")
            zread = step("5 Close-up re-read\n+ label judge")
            decide = step("6 Decide\nfile / ask / retake")
            gate >> Edge(label="sharp") >> read >> planes >> zsel >> zread >> decide
            gate >> Edge(label="blurry: retake,\nno model call", style="dashed") >> decide
        with Cluster("What changed?: POST /rescan, OpenCV 5 first (experimental)", graph_attr={"bgcolor": "#ffffff"}):
            rgate = step("1 Photo gate\n(same as fill)")
            align = step("2 Align to the last photo\n(OpenCV 5: ALIKED + LightGlue,\nMAGSAC homography)")
            judge = step("3 Each known thing:\nstill there / moved /\nnot seen / can't compare\n+ spots that look new")
            rread = step("4 Read marked spots\nonly if the person asks\n(at most 6 crops)")
            rgate >> Edge(label="sharp") >> align >> judge >> Edge(label="person asks", style="dashed") >> rread
        counter = Dynamodb("Daily scan\ncounter")
        params = SystemsManagerParameterStore("On/off switch\n+ API key")
        logs = CloudwatchLogs("Logs\n(codes, counts only)")
        repo = ECR("Engine image")

    claude = Blank("Anthropic API\nClaude Opus 5.5 (vision)\nHaiku 5.5 (judge)", shape="box", style="rounded,filled",
                   fillcolor="#fbf1dc", color="#8a5a00", width="2.6", height="0.9", fixedsize="true", labelloc="c")

    with Cluster("Deploy (no stored keys)", graph_attr={"bgcolor": "#fbf6ec", "fontname": "Helvetica"}):
        gh = Github("GitHub Actions\nmain branch")
        role = IAMRole("Deploy role\n(OIDC, 1 h)")

    person >> Edge(label="sticker photo") >> igate
    imatch >> Edge(label="suggestions;\nperson chooses", color="#1f6f5c") >> pick
    person >> Edge(label="compartment photo") >> outline
    outline >> Edge(label="person's corners") >> warp
    warp >> Edge(label="person drags lines,\nconfirms", color="#1f6f5c") >> twin
    person >> Edge(label="shelf photo") >> gate
    decide >> Edge(label="person confirms list", color="#1f6f5c") >> twin
    person >> Edge(label="same shelf again\n+ the kept last photo") >> rgate
    judge >> Edge(label="questions, no model call;\nperson answers, gone → Unplaced", color="#1f6f5c") >> twin
    rread >> Edge(label="1 admission") >> claude
    params >> Edge(style="dotted") >> gate
    counter >> Edge(label="admit", style="dotted") >> gate
    read >> Edge(label="1 call") >> claude
    iread >> Edge(label="1 call") >> claude
    zread >> Edge(label="≤ 4 + 4 calls") >> claude
    decide >> Edge(style="dotted") >> logs
    gh >> Edge(label="OIDC token") >> role >> Edge(label="push image,\nupdate stack") >> repo
