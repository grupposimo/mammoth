from typing import List
import torch.nn.functional as F
import torch
from torch.utils.data import DataLoader, TensorDataset
from tqdm import tqdm
try:
    import clip
except ImportError:
    raise ImportError("Please install the CLIP package by running: pip install git+https://github.com/openai/CLIP.git")

from datasets.utils.continual_dataset import ContinualDataset
from models.star_prompt_utils.generative_replay import MixtureOfGaussiansModel


class TextEncoder(torch.nn.Module):
    def __init__(self, clip_model):
        super().__init__()
        self.transformer = clip_model.transformer
        self.positional_embedding = clip_model.positional_embedding
        self.ln_final = clip_model.ln_final
        self.text_projection = clip_model.text_projection
        self.dtype = clip_model.dtype

    def forward(self, x, tokenized_prompts):
        x = x + self.positional_embedding.type(self.dtype)
        x = x.permute(1, 0, 2)
        x = self.transformer(x)
        x = x.permute(1, 0, 2)
        x = self.ln_final(x).type(self.dtype)
        x = x[torch.arange(x.shape[0]), tokenized_prompts.argmax(dim=-1)] @ self.text_projection
        return x


class Prompter(torch.nn.Module):

    distributions: List[MixtureOfGaussiansModel]
    token_suffix: torch.Tensor
    token_prefix: torch.Tensor

    def __init__(self, args, num_classes: int, dataset: ContinualDataset, device='cpu'):
        super().__init__()
        self.args = args
        self.num_classes = num_classes
        self.dataset = dataset
        self.device = device

        self.clip_model, self.clip_preprocess = clip.load(args.clip_backbone, self.device)

        for p in self.clip_model.parameters():
            p.requires_grad = False

        self.class_names = dataset.get_class_names()
        self.setup_text_prompting()
        self.clip_logit_scale = self.clip_model.logit_scale

        embed_dim = self.clip_model.visual.output_dim
        self.distributions = torch.nn.ModuleList([MixtureOfGaussiansModel(embed_dim, n_components=self.args.gr_mog_n_components,
                                                                          n_iters=self.args.gr_mog_n_iters)
                                                  for _ in range(self.num_classes)]).to(self.device)

    def compute_ortho_loss(self, cur_classes: int, frozen_past_classes=0) -> torch.Tensor:

        # (num_classes, 1, clip_size)
        cur_coop_p = self.prompt_parameters[frozen_past_classes:cur_classes]
        ortho_loss_coop = 0
        if frozen_past_classes > 0:
            past_coop_p = self.prompt_parameters[:frozen_past_classes].detach()
            ortho_loss_coop = (torch.matmul(cur_coop_p.permute(1, 0, 2), past_coop_p.permute(1, 2, 0))**2).mean()

        return ortho_loss_coop

    @torch.no_grad()
    def create_features_dataset(self, current_task: int):

        labels, features = [], []

        for _ti in range(current_task + 1):

            prev_t_size, cur_t_size = self.dataset.get_offsets(_ti)

            for class_idx in range(prev_t_size, cur_t_size):

                current_samples = self.distributions[class_idx](self.args.num_samples_gr)
                features.append(current_samples)
                labels.append(torch.ones((self.args.num_samples_gr)) * class_idx)

        features = torch.cat(features, dim=0)
        labels = torch.cat(labels, dim=0).long()
        return DataLoader(TensorDataset(features, labels), batch_size=self.args.batch_size_gr, shuffle=True, num_workers=0)

    def train_alignment_epoch(self, optim: torch.optim.Optimizer, current_task: int):
        offset_1, offset_2 = self.dataset.get_offsets(current_task)

        dl = self.create_features_dataset(current_task)

        for i, (image_features, labels) in tqdm(enumerate(dl), total=len(dl), desc='GR first stage epoch'):
            if self.args.debug_mode and i > 3:
                break
            optim.zero_grad()

            image_features, labels = image_features.to(self.device, dtype=self.clip_model.dtype), labels.to(self.device)
            image_features = torch.nn.functional.normalize(image_features, dim=-1)

            text_features = self.compute_keys(0, offset_2)

            text_features = torch.cat((text_features[:offset_1].detach(), text_features[offset_1:offset_2]), dim=0)
            text_features = torch.nn.functional.normalize(text_features, dim=-1)

            clip_logits = torch.einsum('bd,cd->bc', image_features, text_features)
            clip_logits = clip_logits * self.clip_logit_scale.exp()
            loss = F.cross_entropy(clip_logits, labels)

            loss.backward()
            optim.step()

    def align(self, current_task: int):
        optim = torch.optim.SGD(lr=self.args.learning_rate_gr, params=[self.prompt_parameters],
                                momentum=0.0, weight_decay=0.0)

        for e in range(self.args.num_epochs_gr):
            self.train_alignment_epoch(optim, current_task=current_task)

    @torch.no_grad()
    def update_statistics(self, dataset: ContinualDataset, current_task: int):
        offset_1, offset_2 = dataset.get_offsets(current_task)

        features_dict = {i: [] for i in range(offset_1, offset_2)}

        was_training = self.training
        self.eval()

        with tqdm(total=self.args.num_monte_carlo_gr * len(dataset.train_loader), 
                  desc='Updating statistics for first stage Generative Replay') as pbar:
            for _ in range(self.args.num_monte_carlo_gr):
                for i, data in enumerate(dataset.train_loader):
                    if self.args.debug_mode == 1 and i > 3 and min([len(v) for k, v in features_dict.items()]) > self.args.gr_mog_n_components:
                        break
                    inputs, labels = data[0].to(self.device), data[1].to(self.device, dtype=torch.long)

                    if len(inputs.shape) == 5:
                        inputs = inputs[:, 1]
                    clip_query = self.get_query(inputs)

                    for class_idx in labels.unique():
                        features_dict[int(class_idx)].append(clip_query[labels == class_idx])

                    pbar.update(1)

        for class_idx in range(offset_1, offset_2):
            features_class_idx = torch.cat(features_dict[class_idx], dim=0)
            self.distributions[class_idx].fit(features_class_idx.to(self.device))

        if was_training:
            self.train()

    def compute_keys(self, start: int, end: int):
        ctx = self.prompt_parameters[start:end]
        prefix = self.token_prefix[start:end]
        suffix = self.token_suffix[start:end]
        prompts = torch.cat((prefix, ctx, suffix), dim=1)
        tokenized_prompts = self.tokenized_prompts[start:end]
        keys = self.text_encoder(prompts.to(self.clip_model.dtype), tokenized_prompts)
        keys = torch.nn.functional.normalize(keys, dim=-1)
        return keys

    def get_keys(self, cur_classes: int, frozen_past_classes=0):
        if frozen_past_classes > 0:
            with torch.no_grad():
                past_keys = self.compute_keys(0, frozen_past_classes)
            cur_keys = self.compute_keys(frozen_past_classes, cur_classes)
            keys = torch.cat((past_keys.detach(), cur_keys), dim=0)
        else:
            keys = self.compute_keys(0, cur_classes)
        return keys

    def setup_text_prompting(self):
        self.text_encoder = TextEncoder(self.clip_model)

        text_prompts = ["X " + name + "." for name in self.class_names]
        tokenized_prompts = torch.cat([clip.tokenize(p) for p in text_prompts], dim=0).to(self.device)
        self.tokenized_prompts = tokenized_prompts

        with torch.no_grad():
            embedding = self.clip_model.token_embedding(tokenized_prompts).type(self.clip_model.dtype)
        self.register_buffer("token_prefix", embedding[:, :1, :])  # SOS
        self.register_buffer("token_suffix", embedding[:, 2:, :])  # CLS, EOS

        prompt_parameters = torch.empty(self.num_classes, 1, self.clip_model.token_embedding.weight.shape[1], device=self.device, dtype=torch.float32)
        torch.nn.init.normal_(prompt_parameters, std=0.02)
        self.prompt_parameters = torch.nn.Parameter(prompt_parameters)

    @torch.no_grad()
    def get_query(self, x):
        clip_out = self.clip_model.encode_image(x)
        return clip_out

    def get_clip_logits(self, clip_out, keys):
        image_features = torch.nn.functional.normalize(clip_out, dim=-1)
        clip_logits = torch.einsum('bd,cd->bc', image_features, keys)
        clip_logits = clip_logits * self.clip_logit_scale.exp()
        return clip_logits


class Model(torch.nn.Module):
    prompter: Prompter

    def __init__(self, args, num_classes: int, dataset: ContinualDataset, device='cpu'):
        super().__init__()
        self.args = args
        self.num_classes = num_classes
        self.device = device

        self.prompter = Prompter(args, num_classes=num_classes, dataset=dataset, device=device)

    def to(self, device, *args, **kwargs):
        super().to(device, *args, **kwargs)
        self.prompter.to(device, *args, **kwargs)
        self.device = device

        return self

    def train(self, mode=True):
        super().train(False)
        self.prompter.train(False)

        return self

    def forward(self, x: torch.Tensor, cur_classes: int, return_query=False, frozen_past_classes=0):
        clip_out = self.prompter.get_query(x)
        if return_query:
            return clip_out

        keys = self.prompter.get_keys(frozen_past_classes=frozen_past_classes, cur_classes=cur_classes)
        clip_logits = self.prompter.get_clip_logits(clip_out, keys)

        return clip_logits