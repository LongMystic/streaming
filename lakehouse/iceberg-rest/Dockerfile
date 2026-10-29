# Iceberg REST catalog backed by MySQL (Aiven).
# The upstream fixture image only bundles the SQLite JDBC driver, so add MySQL Connector/J
# and start the server with an explicit classpath instead of `java -jar`.
FROM apache/iceberg-rest-fixture:1.10.1

ADD --chown=iceberg:iceberg \
    --checksum=sha256:0353648eaa1c91e0f4020c959abf756bc866ffd583df22ae6b6f6e0cbd43eb44 \
    https://repo1.maven.org/maven2/com/mysql/mysql-connector-j/9.7.0/mysql-connector-j-9.7.0.jar \
    /usr/lib/iceberg-rest/mysql-connector-j.jar

CMD ["java", "-cp", "/usr/lib/iceberg-rest/*", "org.apache.iceberg.rest.RESTCatalogServer"]
