# The engine as a Lambda container image (x86_64). boto3 comes with the base image.
FROM public.ecr.aws/lambda/python:3.12
ENV OPENCV_IO_MAX_IMAGE_PIXELS=50000000
COPY requirements-lambda.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements-lambda.txt -t ${LAMBDA_TASK_ROOT}
# OpenCV 5 feature models (ALIKED + LightGlue ONNX), hash-checked; the build fails on a mismatch
COPY tools/fetch_models.py /tmp/fetch_models.py
RUN python /tmp/fetch_models.py ${LAMBDA_TASK_ROOT}/models
ENV GP_MODELS=${LAMBDA_TASK_ROOT}/models
COPY verifier/ ${LAMBDA_TASK_ROOT}/verifier/
COPY service/ ${LAMBDA_TASK_ROOT}/service/
COPY web/ ${LAMBDA_TASK_ROOT}/web/
CMD ["service.handler.handler"]
