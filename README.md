# OLIM - **O**pen **L**abeller for **I**terative **M**achine Learning


> Under high development

Objetivo: rotular base de dados

passo 1: definir a base de dados, salvar isso de alguma forma.
passo 1.1: definir rotulos possiveis para essa base de dados.
passo 2: definir ter diferentes formas de rotulacao
passo 2.1: rotulo unico: dado uma lista de rotulos, escolher um.
passo 2.2: mais de um rotulo: dado uma lista de rotulos, poder selecionar mais de um
passo 2.3: 2.1 OU 2.2 + campo de rotulo extra.
passo 2.4: dar qualidade ao rotulo: grau de certeza, observacao, caracteristica positiva / negativa, user-inputted.
passo 3: definir pipeline de treinamento
passo 3.1: transformacao: como o dado deve ser inputado antes da vetorizacao, limpeza, escolha de features especificas, forma de injecao.
passo 3.2: vetorizacao: como o dado deve ter sua representacao vetorial, como isso sera feito (escolha de algoritimos, dimensionalidade, etc.)
passo 3.3: treinamento: train vs test, qual/quais algoritimos treinar?
passo 3.4: qual o trigger para "re-treinamento"? quando novo batch de dados rotulados aparecer? sazonalmente? manualmente?
passo 3.5: acompanhar pipeline
passo 4: servir modelos treinados (predict)
passo 5: surrogate model: poder inferir novos rotulos atraves de LLMs
passo 5.1: definir metodologia, exemplo:
  para cada (entrada NAO rotulada := entry) na (base de dados := db):
    define (entradas ROTULADAS parecidas com entry := similar_entries)
    define (rotulos inferidos pelo LLM dado como contexto entry + similar_entries + rotulos possiveis := inferred)
    salva inferred no db com assinatura do LLM e contexto utilizado.


cada uma dessas coisas requer discussoes BEM importantes sobre tipos de dados, como salvar, como rodar, CPU/GPU, sistema distribuido, conexoes, infra, defaults... anyway.
