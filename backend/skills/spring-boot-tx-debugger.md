---
id: spring-boot-tx-debugger
name: Spring transaction debugger
description: Inspect transaction boundaries and AOP proxies when a service method fails inside a transaction.
domain: Spring Boot
triggers: TransactionSystemException,UnexpectedRollbackException,CglibAopProxy
commands: where|locals|print this
---

When a frame sits inside CglibAopProxy or a @Transactional method, capture `this`, the transaction status if it is a local, and the exception message. Do not recommend suspending every request thread. Explain whether the failure happened before or after commit.
