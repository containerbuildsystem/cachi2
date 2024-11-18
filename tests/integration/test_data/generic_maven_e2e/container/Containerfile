FROM docker.io/ibmjava:11-jdk

RUN cp -r /tmp/generic_maven_e2e-output/deps/generic/ /deps

CMD ["java", "-cp", "/deps/ant.jar:/deps/ant-launcher.jar", "org.apache.tools.ant.Main", "-version"]
