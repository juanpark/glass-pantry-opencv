# The engine as a Lambda container image (x86_64). boto3 comes with the base image.
FROM public.ecr.aws/lambda/python:3.12
COPY requirements-lambda.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements-lambda.txt -t ${LAMBDA_TASK_ROOT}
COPY verifier/ ${LAMBDA_TASK_ROOT}/verifier/
COPY service/ ${LAMBDA_TASK_ROOT}/service/
COPY web/ ${LAMBDA_TASK_ROOT}/web/
CMD ["service.handler.handler"]
