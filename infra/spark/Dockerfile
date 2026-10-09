# Spark 3.5.3 + Iceberg 1.7.1 + Kafka source, with all jars baked in at build
# time (no Ivy downloads at runtime -> reproducible, works offline after build).
FROM apache/spark:3.5.3-python3

USER root
ARG ICEBERG_VERSION=1.7.1
ARG SPARK_VERSION=3.5.3
ARG SCALA=2.12
ARG MAVEN=https://repo1.maven.org/maven2

RUN set -eux; cd /opt/spark/jars; \
    for url in \
      "${MAVEN}/org/apache/iceberg/iceberg-spark-runtime-3.5_${SCALA}/${ICEBERG_VERSION}/iceberg-spark-runtime-3.5_${SCALA}-${ICEBERG_VERSION}.jar" \
      "${MAVEN}/org/apache/iceberg/iceberg-aws-bundle/${ICEBERG_VERSION}/iceberg-aws-bundle-${ICEBERG_VERSION}.jar" \
      "${MAVEN}/org/apache/spark/spark-sql-kafka-0-10_${SCALA}/${SPARK_VERSION}/spark-sql-kafka-0-10_${SCALA}-${SPARK_VERSION}.jar" \
      "${MAVEN}/org/apache/spark/spark-token-provider-kafka-0-10_${SCALA}/${SPARK_VERSION}/spark-token-provider-kafka-0-10_${SCALA}-${SPARK_VERSION}.jar" \
      "${MAVEN}/org/apache/kafka/kafka-clients/3.4.1/kafka-clients-3.4.1.jar" \
      "${MAVEN}/org/apache/commons/commons-pool2/2.11.1/commons-pool2-2.11.1.jar" \
      "${MAVEN}/org/postgresql/postgresql/42.7.4/postgresql-42.7.4.jar" ; do \
        wget -q "$url"; \
    done; \
    mkdir -p /opt/agentshield/checkpoints /opt/agentshield/state; \
    chown -R spark:spark /opt/agentshield

COPY --chown=spark:spark infra/spark/log4j2.properties /opt/spark/conf/log4j2.properties
COPY --chown=spark:spark streaming /opt/agentshield/streaming

USER spark
WORKDIR /opt/agentshield
ENV PYTHONPATH=/opt/agentshield \
    SPARK_MASTER=local[4] \
    SPARK_DRIVER_MEMORY=1536m

CMD ["bash", "-c", "exec /opt/spark/bin/spark-submit --master \"$SPARK_MASTER\" --driver-memory \"$SPARK_DRIVER_MEMORY\" --conf spark.ui.port=4040 --conf spark.driver.extraJavaOptions=-Divy.home=/tmp/.ivy2 /opt/agentshield/streaming/spark_job.py"]
