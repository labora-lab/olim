# import json
# from pathlib import Path
# from threading import Thread
# from time import sleep, time

# import active_learning as al
# from icecream import ic
# from numpy.random import default_rng

# from ..settings import RANDOM_SEED, WORK_PATH

# learners_cache = {}

# def get_rng() -> ...:
#     if RANDOM_SEED is None:
#         seed = int(time())
#     else:
#         seed = RANDOM_SEED
#     ic(f"Created generator using seed: {seed}")
#     return default_rng(seed=seed)

# def get_WORK_PATH() -> Path:
#     WORK_PATH = Path(WORK_PATH)
#     if not WORK_PATH.is_dir():
#         WORK_PATH.mkdir(parents=True)
#     return WORK_PATH.absolute()


# def get_data(project_id: int) -> ...:
#     WORK_PATH = get_WORK_PATH().joinpath(str(project_id))
#     with WORK_PATH.joinpath("data.json").open("r") as f:
#         data = json.load(f)
#     return data


# def get_label_dir(project_id: int, label_id: int) -> Path:
#     WORK_PATH = get_WORK_PATH()
#     label_dir = WORK_PATH.joinpath("active-learning", str(project_id), str(label_id))
#     print(label_dir)
#     if not label_dir.is_dir():
#         label_dir.mkdir(parents=True)
#     return label_dir


# def instanciate_al(project_id: int, label_id: int, values) -> None:
#     data = get_data(project_id)
#     learner_path = get_label_dir(project_id, label_id).joinpath("learner")
#     print(f"Instanciating learner for project {project_id}, label {label_id}")
#     learner = al.public_api.ActiveLearningBackend(
#         data, values, save_path=learner_path, rng=get_rng()
#     )
#     print(f"Storing learner for project {project_id}, label {label_id}")
#     learner.save(learner_path)
#     learners_cache[label_id] = learner


# def get_learner(project_id: int, label_id: int) -> al.public_api.ActiveLearningBackend:
#     if label_id in learners_cache:
#         return learners_cache[label_id]
#     else:
#         data = get_data(project_id)
#         print(f"Learner for project {project_id}, label {label_id} not on cache, loading.")
#         learner_path = get_label_dir(project_id, label_id).joinpath("learner")
#         learner = al.public_api.ActiveLearningBackend.load(
#             learner_path, data, rng=get_rng()
#         )
#         learners_cache[label_id] = learner
#         return learner


# def save_learner(project_id: int, label_id: int):
#     learner = learners_cache[label_id]
#     learner_file = get_label_dir(project_id, label_id).joinpath("learner")
#     # print(learner._dataset)
#     learner.save(learner_file)


# def create_learner(project_id: int, label_id: int, values: ...):
#     label_dir = get_label_dir(project_id, label_id)
#     Thread(
#         target=instanciate_al,
#         kwargs={"project_id": project_id, "label_id": label_id, "values": values},
#     ).start()
#     return label_id, label_dir


# class LabelRequest(Resource):
#     def put(self):
#         try:
#             req = models.LabelRequestModel(**dict(request.form))
#             learner = get_learner(req.app_key, req.label_id)
#         except Exception as e:
#             return {"message": f"Failed to get entry to label: {e}"}, 500
#         else:
#             return {
#                 "label_id": req.label_id,
#                 "entry_id": learner.request_next_entry(),
#                 "messages": learner.metrics_strs
#             }


# class LabelValue(Resource):
#     def put(self):
#         try:
#             req = models.LabelValueModel(**dict(request.form))
#             learner = get_learner(req.app_key, req.label_id)
#             learner.submit_labelling(req.entry_id,
#                                      al.public_api.Labelling(req.value),
#                                      req.user_id,
#                                      req.timestamp)
#             save_learner(req.app_key, req.label_id)
#         except Exception as e:
#             return {"message": f"Failed adding value to label?: {e}"}, 500
#         else:
#            return {"label_id": req.label_id, "entry_id": req.entry_id, "timestamp": req.timestamp}


# class LabelDelete(Resource):
#     def delete(self):
#         req = models.LabelRequestModel(**json.loads(request.json))
#         learners_cache.pop(req.label_id)
#         label_dir = get_label_dir(req.app_key, req.label_id)
#         label_dir.rmdir()
#         return {"label_id": req.label_id}


# class SyncLabel(Resource):
#     def put(self):
#         req = models.SyncLabelModel(**json.loads(request.json))
#         values, label = req.values, req.label
#         label_id = label.get("label_id")

#         if not label_id:
#             label_id, _ = create_learner(req.app_key, values)

#         # FIXME Load learner
#         sleep(2)
#         learner = get_learner(req.app_key, label_id)
#         print(label["entries"])
#         learner.sync_labelling(label["entries"])
#         learner_file = get_label_dir(req.app_key, label_id).joinpath("learner")
#         learner.save(learner_file)

#         return {"al_key": label_id}


# class ExportPredictions(Resource):
#     def put(self):
#         try:
#             req = models.ExportPredictionsModel(**json.loads(request.json))
#             learner = get_learner(req.app_key, req.label_id)
#             preds = learner.export_preditictions(alpha=req.alpha)
#             return {"status": "success", "predictions": preds}
#         except Exception as e:
#             print("Error processing export:", e)
#             print(req)
#             return {"message": str(e)}, 500

